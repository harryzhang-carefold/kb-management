"""Lossless bounded partitioning for any long document, not specific workbooks."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.pageindex_engine import _split_by_heading


@pytest.mark.parametrize('text', [
    'plain text ' * 40,
    '## First worksheet\n' + 'long row🙂 ' * 60 + '\n## Next worksheet\nShort.',
    '# Short introduction\nHi\n## Long section\n' + 'business method ' * 60,
    '# Only heading\n' + 'x' * 500,
    '## First\r\n' + '汉字🙂' * 90 + '\r\n## Last\r\nEnd',
])
def test_long_sections_are_bounded_and_do_not_lose_source_text(text):
    parts = _split_by_heading(text, limit=80)
    assert ''.join(piece for _, piece in parts) == text
    assert all(0 < len(piece) <= 80 for _, piece in parts)
    position = 0
    for start, piece in parts:
        assert start == position
        position += len(piece)


def test_partition_prefers_available_heading_boundaries():
    text = '# One\n' + 'a' * 30 + '\n## Two\n' + 'b' * 40
    parts = _split_by_heading(text, limit=60)
    assert parts[1][0] == text.index('## Two')


def test_compound_tree_keeps_valid_local_depth_and_node_budgets(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.services import pageindex_engine as engine
    text = 'x' * (engine.MAX_DOC_CHARS + 10)
    document = SimpleNamespace(id='fixture', file_type='txt', is_deleted=False, full_text=text,
                               filename='Unseen large document', meta={})
    db = MagicMock(); db.query.return_value.filter_by.return_value.with_for_update.return_value.one.return_value = document
    def tree(piece, start, prefix):
        node = {'node_id': prefix + '.1.1.1', 'title': 'Actual subsection', 'summary': '',
                'start': start, 'end': start + len(piece), 'children': []}
        for depth in (2, 1, 0):
            node = {'node_id': prefix + '.1' * depth, 'title': 'Actual section', 'summary': '',
                    'start': start, 'end': start + len(piece), 'children': [node]}
        return node
    monkeypatch.setattr(engine, '_llm_build_piece', tree)
    monkeypatch.setattr('app.knowledge.text_evidence.publish', lambda *a: None)
    result = engine.build_tree_index(document, db)
    assert result['status'] == 'ok' and result['piece_count'] == 2
    assert len(result['root']['children']) == 2


def test_build_concurrency_is_bounded_and_source_order_is_preserved(monkeypatch):
    import threading
    from app.services import pageindex_engine as engine
    barrier = threading.Barrier(2); lock = threading.Lock(); active = 0; peak = 0
    monkeypatch.setattr(engine.settings, 'pageindex_build_concurrency', 2)
    def build(piece, start, prefix):
        nonlocal active, peak
        with lock:
            active += 1; peak = max(peak,active)
        barrier.wait(timeout=2)
        with lock: active -= 1
        return {'start':start,'piece':piece,'id':prefix}
    monkeypatch.setattr(engine,'_llm_build_piece',build)
    pieces = [(i*10,str(i)) for i in range(6)]
    result = engine._build_pieces(pieces)
    assert peak == 2
    assert [r['start'] for r in result] == [p[0] for p in pieces]
    assert [r['id'] for r in result] == [f'n1.{i+1}' for i in range(6)]


def test_invalid_model_tree_is_not_published_after_an_invalid_retry(monkeypatch):
    import json
    from app.services import pageindex_engine as engine
    monkeypatch.setattr(engine.llm_client,'chat',lambda *a,**kw: json.dumps({'root': {
        'title':'Incorrect range','summary':'','start':0,'end':5000,'children':[]}}))
    with pytest.raises(ValueError, match='Tree retry failed'):
        engine._llm_build_piece('Original text',0,'n1')
