"""MCP server round trip: a real MCP client (in memory transport, same
protocol as stdio) lists the tools and calls both against the test
database. Proves the server an external MCP client like Claude connects
to actually works, without subprocesses."""

import pytest
from mcp.client.client import Client

from mcp_server.server import build_server
from tests.integration.test_knowledge import SLEEP_DOC, ingest

pytestmark = pytest.mark.integration


async def test_mcp_round_trip(client, app, seeded, auth_header):
    ops = await auth_header("ops@a.caremesh.org")
    await ingest(client, ops)

    server = build_server(app.state.session_factory, org_name="Test Org A")
    async with Client(server) as mcp_client:
        tools = await mcp_client.list_tools()
        names = sorted(tool.name for tool in tools.tools)
        assert names == ["get_platform_stats", "search_resources"]

        found = await mcp_client.call_tool(
            "search_resources", {"query": "trouble with sleep during exams"}
        )
        payload = found.structured_content
        assert payload["organization"] == "Test Org A"
        assert payload["results"], "expected the ingested document to be found"
        assert payload["results"][0]["document"] == SLEEP_DOC["title"]
        assert "fictional" in payload["note"]

        stats = await mcp_client.call_tool("get_platform_stats", {})
        counts = stats.structured_content
        assert counts["organization"] == "Test Org A"
        assert counts["documents_in_library"] == 1
        assert counts["ai_requests"] >= 0
        assert isinstance(counts["workflows"], list)


async def test_mcp_server_is_tenant_scoped(app, seeded):
    """An org name that does not exist yields an error, never another
    tenant's data."""
    server = build_server(app.state.session_factory, org_name="No Such Org")
    async with Client(server) as mcp_client:
        found = await mcp_client.call_tool("search_resources", {"query": "sleep"})
        assert "not found" in found.structured_content["error"]
