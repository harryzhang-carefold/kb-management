"""The schema visible to the Agent must match the Authority before dispatch."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from mcp.server.mcpserver import MCPServer
from app.knowledge.mcp_tools import register
from app.knowledge.spreadsheet_service import Read


def test_mcp_exposes_authority_constraints_for_all_evidence_tools():
    server = MCPServer('schema-contract')
    register(server)
    tools = {tool.name: tool.input_schema for tool in asyncio.run(server.list_tools())}
    for name in ('pageindex_read_pages', 'spreadsheet_read_cells'):
        fields = tools[name]['properties']
        assert fields['max_chars']['minimum'] == 2000
        assert fields['max_chars']['maximum'] == 24000
        assert fields['version']['pattern'] == Read.model_json_schema()['properties']['version']['pattern']
    assert tools['spreadsheet_get_structure']['properties']['document_id']['pattern'] == Read.model_json_schema()['properties']['document_id']['pattern']
    assert tools['pageindex_read_pages']['properties']['pages']['maxItems'] == 8
    assert tools['spreadsheet_read_cells']['properties']['filters']['maxItems'] == 10
    assert tools['spreadsheet_verify_citations']['properties']['citations']['maxItems'] == 3
    assert tools['knowledge_discover']['properties']['limit']['maximum'] == 50


def test_text_metadata_preserves_distinct_native_reference_pair(monkeypatch):
    import base64
    import json
    from app.knowledge.access import KBKnowledgeService, request_headers
    monkeypatch.setattr('app.core.security.create_view_token', lambda *args: 'local-view-token')
    service = KBKnowledgeService.__new__(KBKnowledgeService)
    text_id, text_version = 'a' * 64, 'b' * 64
    native = {'document_id': '11111111-1111-1111-1111-111111111111', 'version': 'c' * 64}
    references = {'parsed_text': {'document_id': text_id, 'version': text_version}, 'native_cells': native}
    service.document_read_methods = {text_id: {'evidence': references,
        'read_methods': ['pageindex_read_pages', 'spreadsheet_read_cells']}}
    token = request_headers.set({'x-carefold-interaction-scope': base64.urlsafe_b64encode(json.dumps({'actorId': 'local'}).encode()).decode()})
    try:
        metadata = service.metadata({'id': text_id, 'version': text_version, 'source_id': 'local-source',
            'title': 'Rules.xlsx', 'source_type': 'xlsx', 'page_count': 1,
            'source_metadata': {'kb_id': 'local-kb', 'kb_document_id': native['document_id']}})
        assert metadata['document_id'] == text_id
        assert metadata['evidence'] == references
        assert metadata['evidence']['native_cells'] != metadata['evidence']['parsed_text']
        assert metadata['read_methods'] == ['pageindex_read_pages', 'spreadsheet_read_cells']
    finally:
        request_headers.reset(token)


def test_invalid_cell_filter_returns_actionable_selector_constraint():
    import pytest
    from types import SimpleNamespace
    from mcp.shared.exceptions import MCPError
    from app.knowledge.mcp_tools import invoke
    from app.knowledge import spreadsheet
    service = SimpleNamespace(call=lambda *args: spreadsheet.select(
        {'sheets': [{'id': 'sheet'}]}, 'sheet', cell_range='A1:C4',
        filters=[{'column_id': 'B', 'operator': 'eq', 'value': 'private-value'}]))
    with pytest.raises(MCPError) as error:
        invoke(service, 'spreadsheet_read_cells', {}, {})
    assert error.value.error.code == -32602
    diagnostic = error.value.error.data['validation_errors'][0]
    assert diagnostic['loc'] == ['filters']
    assert 'table_id' in diagnostic['msg'] and 'spreadsheet_get_structure' in diagnostic['msg']
    assert 'private-value' not in str(error.value.error.data)
