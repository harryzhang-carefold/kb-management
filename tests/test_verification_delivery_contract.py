from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_verifiers_request_directly_deliverable_checked_claims_without_unsupported_explanation():
    pageindex = (ROOT / 'backend/app/knowledge/service.py').read_text()
    spreadsheet = (ROOT / 'backend/app/knowledge/mcp_tools.py').read_text()
    for source in [pageindex, spreadsheet]:
        assert 'concise user-facing claims' in source
        assert 'Runtime can display it directly with its source after checked' in source
        assert 'do not put unsupported explanation into the claim' in source
