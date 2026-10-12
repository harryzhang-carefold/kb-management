"""Register the inherited four evidence tools on the existing 9100 MCP server."""
from .access import KBKnowledgeService, request_headers
from .reading import serialize
from .service import ID, Page, Citation, OPERATIONS


def register(mcp):
    def call(name, values):
        headers = request_headers.get()
        service = KBKnowledgeService()
        result = service.call(name, values, headers.get('x-carefold-interaction-scope'),
                              headers.get('x-carefold-scope-issued-at'),
                              headers.get('x-carefold-scope-signature'))
        return serialize(result)

    @mcp.tool(description=OPERATIONS['pageindex_list_documents'][1])
    def pageindex_list_documents(offset: int = 0, limit: int = 20) -> str:
        return call('pageindex_list_documents', {'offset': offset, 'limit': limit})

    @mcp.tool(description=OPERATIONS['pageindex_get_structure'][1])
    def pageindex_get_structure(document_id: ID, version: ID, node_id: str | None = None,
                               offset: int = 0, limit: int = 20) -> str:
        return call('pageindex_get_structure', {'document_id': document_id, 'version': version,
                    'node_id': node_id, 'offset': offset, 'limit': limit})

    @mcp.tool(description=OPERATIONS['pageindex_read_pages'][1])
    def pageindex_read_pages(document_id: ID, version: ID, pages: list[Page],
                            cursor: str | None = None, max_chars: int = 20000) -> str:
        return call('pageindex_read_pages', {'document_id': document_id, 'version': version,
                    'pages': pages, 'cursor': cursor, 'max_chars': max_chars})

    @mcp.tool(description=OPERATIONS['pageindex_verify_citations'][1])
    def pageindex_verify_citations(document_id: ID, version: ID, citations: list[Citation]) -> str:
        return call('pageindex_verify_citations', {'document_id': document_id, 'version': version,
                    'citations': [item.model_dump() for item in citations]})
