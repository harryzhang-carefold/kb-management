"""Auto retrieval can rank literal candidates without asserting semantic support.

Explicit PageIndex mode, weak/stale candidates, source scopes and the downstream
original-evidence verification path remain unchanged.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services import pageindex_engine as engine


def document(ident='source-a', text='alpha beta gamma exact material. ', stale=False):
    root = {'node_id': 'n1', 'title': 'Root', 'summary': 'Root summary',
            'start': 0, 'end': len(text), 'children': []}
    tree = {'status': 'ok', 'full_text_chars': len(text) - int(stale), 'root': root}
    return SimpleNamespace(id=ident, kb_id='authorized-kb', filename='Document', file_type='txt',
                           is_deleted=False, indexed_at=None, full_text=text,
                           meta={'index_type': 'pageindex', engine.TREE_KEY: tree})


def db_for(docs):
    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def all(self): return docs
    return SimpleNamespace(query=lambda *_args: Query())


@pytest.fixture
def capture(monkeypatch):
    calls = []
    def semantic(messages, **kwargs):
        calls.append(messages)
        return json.dumps({'selected': [{'doc_id': 'source-a', 'node_id': 'n1', 'relevance': 0.91}]})
    monkeypatch.setattr(engine.llm_client, 'chat', semantic)
    def build(doc, tree, node, score, **metadata):
        return {'document_id': doc.id, 'content': doc.full_text[node['start']:node['end']][:engine.MAX_CONTENT_CHARS],
                'score': score, 'metadata': {'node_id': node['node_id'], **metadata}}
    monkeypatch.setattr(engine, '_build_result', build)
    return calls


def test_auto_strong_literal_candidates_require_no_semantic_model(capture):
    docs = [document()]
    hits, _, extra = engine.retrieve('authorized-kb', 'alpha beta gamma', 5, db=db_for(docs), prefer_lexical=True)
    assert capture == []
    assert [h['document_id'] for h in hits] == ['source-a']
    assert extra['candidate_mode'] == 'lexical_direct'
    assert extra['attempts'] == 0
    assert extra['semantic_selection'] is False
    assert hits[0]['metadata']['selected_by'] == 'lexical_candidate'
    assert 'checked' not in json.dumps(hits)


def test_explicit_pageindex_keeps_the_existing_semantic_selector(capture):
    hits, _, extra = engine.retrieve('authorized-kb', 'alpha beta gamma', 5, db=db_for([document()]))
    assert len(capture) == 1
    assert hits and extra['attempts'] == 1
    assert extra['candidate_mode'] != 'lexical_direct'


@pytest.mark.parametrize('query,text,stale', [
    ('unseen conceptual wording', 'alpha beta gamma material', False),
    ('alpha beta gamma', 'alpha beta gamma material', True),
    ('alpha beta gamma delta epsilon zeta', 'alpha beta gamma material', False),
    ('alpha beta gamma 731', 'alpha beta gamma 732 material', False),
    ('alpha beta gamma 7', 'alpha beta gamma 8 material', False),
    ('alpha beta gamma', ('unrelated ' * 400) + 'alpha beta gamma', False),
    ('alpha', 'alpha material', False),
])
def test_weak_stale_missing_identity_or_hidden_excerpt_does_not_skip_semantics(capture, query, text, stale):
    hits, _, extra = engine.retrieve('authorized-kb', query, 5, db=db_for([document(text=text, stale=stale)]), prefer_lexical=True)
    assert len(capture) == 1
    assert hits
    assert extra['candidate_mode'] != 'lexical_direct'


def test_tied_candidates_remain_candidates_not_an_implicit_entity_selection(capture):
    docs = [document('source-a'), document('source-b')]
    hits, _, extra = engine.retrieve('authorized-kb', 'alpha beta gamma', 5, db=db_for(docs), prefer_lexical=True)
    assert capture == []
    assert {h['document_id'] for h in hits} == {'source-a', 'source-b'}
    assert extra['semantic_selection'] is False


def test_specific_regions_deduplicate_parent_ranges_and_preserve_source_filter(capture):
    doc = document(text='alpha beta gamma. other unrelated material. ')
    root = doc.meta[engine.TREE_KEY]['root']
    root['children'] = [{'node_id': 'n1.1', 'title': 'Specific', 'summary': 'Specific',
                         'start': 0, 'end': len('alpha beta gamma.'), 'children': []}]
    hits, _, _ = engine.retrieve('authorized-kb', 'alpha beta gamma', 5, db=db_for([doc]), prefer_lexical=True)
    assert capture == []
    assert len(hits) == 1 and hits[0]['metadata']['node_id'] == 'n1.1'
    # A file-type exclusion is applied before ranking and cannot become a hit.
    hits, _, extra = engine.retrieve('authorized-kb', 'alpha beta gamma', 5,
                                     filters={'file_type': 'pdf'}, db=db_for([doc]), prefer_lexical=True)
    assert hits == [] and extra['empty_reason'] == 'no_pageindex_docs'


def test_auto_entrypoint_enables_literal_candidates_without_rewriting_query_or_scope(monkeypatch):
    import ast
    from typing import Optional
    path = Path(__file__).resolve().parents[1] / 'backend/app/services/auto_retrieval.py'
    node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_pageindex_leg')
    namespace = {'Optional': Optional, 'LEG_PAGEINDEX': 'pageindex'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), namespace)
    seen = []
    def retrieve(kb_id, query, top_n, **kwargs):
        seen.append((kb_id, query, top_n, kwargs))
        return [{'metadata': {'selected_by': 'lexical_candidate'}}], 1, {'candidate_mode': 'lexical_direct'}
    monkeypatch.setattr(engine, 'retrieve', retrieve)
    session = object()
    hits, _, err = namespace['_pageindex_leg']('only-authorized-kb', 'original query', 4, {'file_type': 'txt'}, session)
    assert seen == [('only-authorized-kb', 'original query', 4, {
        'filters': {'file_type': 'txt'}, 'db': session, 'prefer_lexical': True})]
    assert err is None and hits[0]['metadata']['leg'] == 'pageindex'


def test_lexical_metadata_never_misrepresents_a_semantic_judgment(monkeypatch):
    from app.core import database
    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
    monkeypatch.setattr(database, 'SessionLocal', Session)
    monkeypatch.setattr(engine, '_first_chunk_anchor', lambda *_args: ('anchor', 0))
    doc = document()
    tree = doc.meta[engine.TREE_KEY]
    hit = engine._build_result(doc, tree, tree['root'], 1.0,
                               selected_by='lexical_candidate', lex_coverage=1.0, lex_matched=3)
    assert hit['metadata']['score_source'] == 'lexical_coverage'
    assert hit['metadata']['selected_by'] == 'lexical_candidate'
    assert hit['content'] == doc.full_text
    assert 'support_status' not in hit and 'citation_id' not in hit


@pytest.mark.parametrize('prefix', ['', 'shared-prefix'])
def test_semantic_selector_cannot_guess_the_first_document_from_an_ambiguous_id(capture, monkeypatch, prefix):
    monkeypatch.setattr(engine.llm_client, 'chat', lambda *a, **kw: json.dumps({
        'selected': [{'doc_id': prefix, 'node_id': 'n1', 'relevance': 0.99}]}))
    docs = [document('shared-prefix-a'), document('shared-prefix-b')]
    hits, _, extra = engine.retrieve(['kb-a', 'kb-b'], 'unseen conceptual wording', 5, db=db_for(docs))
    assert hits == []
    assert extra['unresolved_selected'][0]['reason'] == 'doc_id_unknown'


def test_semantic_fallback_still_handles_empty_lexical_input_and_errors(capture):
    hits, _, extra = engine.retrieve('authorized-kb', 'a', 5, db=db_for([document()]), prefer_lexical=True)
    assert len(capture) == 1 and hits
    assert extra['candidate_mode'] == 'full_outline'
