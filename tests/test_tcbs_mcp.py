from app.tcbs.client import TCBSMCPClient, extract_tickers


def test_extract_tickers_filters_finance_terms():
    assert extract_tickers("So sánh VCB với BID về PE, ROE và NIM") == ["VCB", "BID"]


def test_client_is_unconfigured_without_token(monkeypatch):
    monkeypatch.delenv("TCBS_MCP_ACCESS_TOKEN", raising=False)
    client = TCBSMCPClient(access_token="")
    assert client.configured is False


def test_client_uses_official_default_endpoint(monkeypatch):
    monkeypatch.delenv("TCBS_MCP_URL", raising=False)
    client = TCBSMCPClient(access_token="demo")
    assert client.url == "https://mcp.tcbs.com.vn/mcp/tcinvest/"
