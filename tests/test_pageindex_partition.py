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
