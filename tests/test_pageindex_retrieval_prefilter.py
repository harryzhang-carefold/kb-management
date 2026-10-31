import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.services import pageindex_engine as engine


def _document(children):
    full_text = ''.join(child['text'] for child in children)
    offset = 0
    nodes = []
    for index, child in enumerate(children, 1):
        end = offset + len(child['text'])
        nodes.append({'node_id': f'n1.{index}', 'title': child['title'], 'summary': child['summary'],
                      'start': offset, 'end': end, 'children': []})
        offset = end
    root = {'node_id': 'n1', 'title': 'Root', 'summary': 'Document root',
            'start': 0, 'end': len(full_text), 'children': nodes}
    tree = {'status': 'ok', 'full_text_chars': len(full_text), 'root': root}
    return SimpleNamespace(id='doc-1', kb_id='kb-1', is_deleted=False, full_text=full_text,
                           filename='Guide', file_type='txt', indexed_at=None,
                           meta={'index_type': 'pageindex', engine.TREE_KEY: tree}), tree


def test_strong_lexical_signal_keeps_roots_and_bounded_deduplicated_candidates():
    doc, tree = _document([
        {'title': 'Exact', 'summary': 'claim reason status guide',
         'text': 'claim reason status guide exact procedure. '},
        *[{'title': f'Other {i}', 'summary': 'unrelated material',
           'text': 'unrelated material and general notes. '} for i in range(100)],
    ])
    filtered = [(doc, tree)]
    ranked, related = engine._lexical_rank(filtered, 'claim reason status guide')
    candidates = engine._lexical_prefilter_candidates(filtered, ranked)
    assert related is True
    assert candidates[0][2]['node_id'] == 'n1'
    assert any(node['node_id'] == 'n1.1' for _doc, _tree, node in candidates)
    assert len(candidates) <= 1 + engine.LEX_PREFILTER_MAX_NODES
    ranges = [(node['start'], node['end']) for _doc, _tree, node in candidates]
    assert len(ranges) == len(set(ranges))
    assert len(candidates) < len(engine._walk_nodes(tree['root']))


def test_weak_lexical_signal_does_not_narrow_the_semantic_outline():
    doc, tree = _document([
        {'title': 'One', 'summary': 'alpha beta', 'text': 'alpha beta content. '},
        {'title': 'Two', 'summary': 'gamma delta', 'text': 'gamma delta content. '},
    ])
    ranked, related = engine._lexical_rank([(doc, tree)], 'unseen semantic synonym')
    assert related is False
    assert engine._lexical_prefilter_candidates([(doc, tree)], ranked) == []


def test_retrieve_uses_bounded_candidates_but_llm_still_selects_the_node(monkeypatch):
    doc, tree = _document([
        {'title': 'Exact', 'summary': 'claim reason status guide',
         'text': 'claim reason status guide exact procedure. '},
        *[{'title': f'Other {i}', 'summary': 'unrelated material',
           'text': 'unrelated material and general notes. '} for i in range(90)],
    ])

    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def all(self): return [doc]

    class DB:
        def query(self, *_args): return Query()

    captured = {}
    def chat(messages, **_kwargs):
        captured['prompt'] = messages[1]['content']
        return json.dumps({'selected': [{'doc_id': 'doc-1', 'node_id': 'n1.1', 'relevance': 0.91}]})

    monkeypatch.setattr(engine.llm_client, 'chat', chat)
    monkeypatch.setattr(engine, '_build_result', lambda document, _tree, node, relevance, **_kwargs: {
        'chunk_id': 'chunk', 'document_id': str(document.id), 'filename': document.filename,
        'chunk_index': 0, 'content': 'selected content', 'score': relevance,
        'match_type': 'pageindex', 'metadata': {'node_id': node['node_id']},
    })
    results, _elapsed, extra = engine.retrieve('kb-1', 'claim reason status guide', 5, db=DB())
    assert [result['metadata']['node_id'] for result in results] == ['n1.1']
    assert extra['candidate_mode'] == 'lexical_prefilter'
    assert extra['candidate_nodes'] < extra['outline_nodes_total']
    assert '[n1.1]' in captured['prompt']
    assert '[n1.90]' not in captured['prompt']


def test_retrieve_keeps_full_outline_when_lexical_signal_is_weak(monkeypatch):
    doc, tree = _document([
        {'title': 'One', 'summary': 'alpha beta', 'text': 'alpha beta content. '},
        {'title': 'Two', 'summary': 'gamma delta', 'text': 'gamma delta content. '},
    ])

    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def all(self): return [doc]

    class DB:
        def query(self, *_args): return Query()

    captured = {}
    def chat(messages, **_kwargs):
        captured['prompt'] = messages[1]['content']
        return json.dumps({'selected': [{'doc_id': 'doc-1', 'node_id': 'n1.2', 'relevance': 0.4}]})
    monkeypatch.setattr(engine.llm_client, 'chat', chat)
    monkeypatch.setattr(engine, '_build_result', lambda document, _tree, node, relevance, **_kwargs: {
        'chunk_id': 'chunk', 'document_id': str(document.id), 'filename': document.filename,
        'chunk_index': 0, 'content': 'selected content', 'score': relevance,
        'match_type': 'pageindex', 'metadata': {'node_id': node['node_id']},
    })
    results, _elapsed, extra = engine.retrieve('kb-1', 'unseen semantic synonym', 5, db=DB())
    assert [result['metadata']['node_id'] for result in results] == ['n1.2']
    assert extra['candidate_mode'] == 'full_outline'
    assert extra['candidate_nodes'] == extra['outline_nodes_total'] == 3
    assert '[n1.1]' in captured['prompt'] and '[n1.2]' in captured['prompt']
