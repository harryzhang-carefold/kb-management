import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.knowledge import source_catalog, spreadsheet, spreadsheet_service, store


def record(table_count=1, column_count=3):
    tables = []
    for table_index in range(table_count):
        tables.append({'id': f'table-{table_index}', 'range': 'A1:C4', 'header_row': 1,
            'first_data_row': 2, 'last_data_row': 4,
            'columns': [{'id': chr(65 + index), 'header': f'Header {index}', 'coordinate': f'{chr(65 + index)}1',
                         'types': ['str']} for index in range(column_count)]})
    return {'version': 'version-1', 'sha256': 'sha-1', 'parser_version': 'xlsx-v3',
        'sheets': [{'id': 'sheet-1', 'name': 'Rules', 'index': 0, 'visibility': 'visible',
                    'max_row': 4, 'max_column': column_count, 'merged_ranges': [],
                    'tables': tables,
                    'cells': {'A2': {'coordinate': 'A2', 'value': 'DO_NOT_PUBLISH', 'type': 'str'}}}]}


def test_structure_summary_exposes_only_bounded_selectors_without_cell_values():
    summary = spreadsheet.structure_summary(record())
    assert summary == {'scope': 'configured_tables', 'complete': True,
        'sheet_count': 1, 'table_count': 1, 'sheets': [{
            'id': 'sheet-1', 'name': 'Rules', 'index': 0, 'visibility': 'visible',
            'max_row': 4, 'max_column': 3, 'tables': [{
                'id': 'table-0', 'range': 'A1:C4', 'header_row': 1,
                'first_data_row': 2, 'last_data_row': 4,
                'columns': [
                    {'id': 'A', 'header': 'Header 0', 'types': ['str']},
                    {'id': 'B', 'header': 'Header 1', 'types': ['str']},
                    {'id': 'C', 'header': 'Header 2', 'types': ['str']},
                ],
            }],
        }]}
    encoded = json.dumps(summary)
    assert 'DO_NOT_PUBLISH' not in encoded
    assert 'cells' not in encoded and 'merged_ranges' not in encoded and 'coordinate' not in encoded


def test_structure_summary_marks_truncation_without_claiming_complete(monkeypatch):
    monkeypatch.setattr(spreadsheet, 'STRUCTURE_SUMMARY_MAX_TABLES', 1)
    monkeypatch.setattr(spreadsheet, 'STRUCTURE_SUMMARY_MAX_COLUMNS', 2)
    summary = spreadsheet.structure_summary(record(table_count=2, column_count=3))
    assert summary['complete'] is False
    assert summary['table_count'] == 2
    assert len(summary['sheets'][0]['tables']) == 1
    assert len(summary['sheets'][0]['tables'][0]['columns']) == 2


def test_existing_published_pointer_is_enriched_from_the_exact_stored_version(monkeypatch):
    current = record()
    calls = []
    monkeypatch.setattr(store, 'get', lambda kind, key: calls.append((kind, key)) or current)
    pointer = source_catalog.native_cells_reference('doc-1', {
        'spreadsheet_evidence': {'document_id': 'doc-1', 'version': 'version-1', 'sha256': 'sha-1'} })
    assert calls == [('spreadsheet_version', 'doc-1:version-1')]
    assert pointer['structure']['complete'] is True
    assert pointer['structure']['sheets'][0]['tables'][0]['id'] == 'table-0'
    assert 'DO_NOT_PUBLISH' not in json.dumps(pointer)


def test_structure_enrichment_fails_closed_to_the_original_versioned_pointer(monkeypatch):
    monkeypatch.setattr(store, 'get', lambda *_args: record() | {'version': 'other-version'})
    original = {'document_id': 'doc-1', 'version': 'version-1', 'sha256': 'sha-1'}
    pointer = source_catalog.native_cells_reference('doc-1', {'spreadsheet_evidence': original})
    assert pointer == original


def test_publish_persists_the_same_bounded_structure_summary(monkeypatch):
    current = record()
    doc = SimpleNamespace(id='doc-1', kb_id='kb-1', is_deleted=False, file_type='xlsx',
                          minio_key='object-key', filename='Rules.xlsx', meta={})
    class Query:
        def filter_by(self, **_kwargs): return self
        def with_for_update(self): return self
        def one(self): return doc
    class DB:
        def query(self, *_args): return Query()
        def flush(self): pass
    monkeypatch.setattr(spreadsheet_service.minio_client, 'get_object', lambda _key: b'fixture')
    monkeypatch.setattr(spreadsheet_service.spreadsheet, 'parse', lambda *_args: current.copy())
    written = []
    monkeypatch.setattr(spreadsheet_service.store, 'put', lambda *args: written.append(args))
    spreadsheet_service.publish(doc, DB())
    pointer = doc.meta['spreadsheet_evidence']
    assert pointer['structure'] == spreadsheet.structure_summary(current)
    assert written and written[0][0] == 'spreadsheet_version'
    assert 'DO_NOT_PUBLISH' not in json.dumps(pointer)


def test_tool_descriptions_prefer_current_complete_structure_without_forcing_it():
    service = (ROOT / 'backend/app/knowledge/service.py').read_text()
    mcp = (ROOT / 'backend/mcp_server.py').read_text()
    for text in [service, mcp]:
        assert 'evidence.native_cells.structure' in text
        assert 'complete=true' in text
        assert 'spreadsheet_get_structure' in text
    assert 'absent/partial' in service
    assert '结构缺失/部分' in mcp
