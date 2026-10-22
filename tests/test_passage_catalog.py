"""Keep source passage identities stable without reprocessing the whole source per sentence."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.knowledge import documents


def test_large_logical_page_normalization_work_is_bounded(monkeypatch):
    text = ' '.join(f'Unique source record {i:05d} has its own condition.' for i in range(1200))
    original = documents.norm
    normalized_chars = 0

    def counted(value):
        nonlocal normalized_chars
        normalized_chars += len(value)
        return original(value)

    monkeypatch.setattr(documents, 'norm', counted)
    passages = documents.passage_catalog(1, text)
    assert len(passages) == 1200
    assert passages[0] == {'id': 'p1-001', 'text': 'Unique source record 00000 has its own condition.'}
    assert passages[-1]['id'] == 'p1-1200'
    assert ' '.join(item['text'] for item in passages) == text
    assert normalized_chars < len(text) * 5


def test_duplicate_passages_keep_their_previous_grouping_and_symbols():
    text = 'Repeated source sentence. Repeated source sentence. A unique condition α ≠ β.'
    assert documents.passage_catalog(3, text) == [
        {'id': 'p3-001', 'text': 'Repeated source sentence. Repeated source sentence.'},
        {'id': 'p3-002', 'text': 'A unique condition α ≠ β.'}]
