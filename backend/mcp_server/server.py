"""CareMesh MCP server: read only tools for an MCP client such as Claude.

Runs over stdio, so it inherits the trust of whoever launched it on this
machine; there is no network listener. Security choices, deliberately
narrow (see docs/THREAT_MODEL.md):

- Allow listed tools only, both read only. No free form SQL, no writes.
- Scoped to one organization, named by MCP_ORG_NAME (defaults to the
  seeded demo org). Cross tenant reads are impossible by construction.
- search_resources returns library excerpts and citations, never
  conversation messages. get_platform_stats returns counts only, never
  content or names.

Start it with: cd backend && uv run python -m mcp_server
"""

import os
from typing import Any

from sqlalchemy import text

from app.application.use_cases.knowledge import KnowledgeService
from app.domain.entities import Organization
from app.infrastructure.ai.embeddings import create_embedding_provider
from app.infrastructure.repositories import (
    SqlChunkRepository,
    SqlDocumentRepository,
    SqlOrganizationRepository,
    SqlRagRetrievalRepository,
)
from app.infrastructure.settings import get_settings

DEFAULT_ORG_NAME = "Evergreen High (fictional)"

DISCLAIMER = (
    "CareMesh is a portfolio simulation, not a real healthcare product; all data is fictional."
)

_STAT_QUERIES = {
    "conversations": "SELECT count(*) FROM conversations WHERE organization_id = :org",
    "messages": (
        "SELECT count(*) FROM messages m JOIN conversations c "
        "ON m.conversation_id = c.id WHERE c.organization_id = :org"
    ),
    "risk_signals": "SELECT count(*) FROM risk_signals WHERE organization_id = :org",
    "documents_in_library": "SELECT count(*) FROM documents WHERE organization_id = :org",
    "ai_requests": "SELECT count(*) FROM ai_requests WHERE organization_id = :org",
    "ai_requests_simulated": (
        "SELECT count(*) FROM ai_requests WHERE organization_id = :org AND simulated"
    ),
}

_WORKFLOWS_BY_STATE = (
    "SELECT workflow_type, state, count(*) FROM workflow_instances "
    "WHERE organization_id = :org GROUP BY workflow_type, state ORDER BY 1, 2"
)


async def _resolve_org(session, org_name: str) -> Organization | None:
    return await SqlOrganizationRepository(session).get_by_name(org_name)


def build_server(session_factory, org_name: str | None = None):
    """Build the MCP server around an existing session factory so tests can
    point it at the test database without subprocesses or env juggling."""
    from mcp.server.mcpserver import MCPServer

    settings = get_settings()
    scoped_org = org_name or os.environ.get("MCP_ORG_NAME", DEFAULT_ORG_NAME)

    server = MCPServer(
        name="caremesh",
        instructions=(
            "Read only access to one CareMesh organization's resource "
            f"library and operational counts. {DISCLAIMER}"
        ),
    )

    @server.tool(
        description=(
            "Search the organization's mental health resource library and "
            "return the best matching excerpts with document citations. "
            "Retrieval only, no generation."
        )
    )
    async def search_resources(query: str) -> dict[str, Any]:
        async with session_factory() as session:
            org = await _resolve_org(session, scoped_org)
            if org is None:
                return {"error": f"Organization '{scoped_org}' not found. Seed the database first."}
            knowledge = KnowledgeService(
                documents=SqlDocumentRepository(session),
                chunks=SqlChunkRepository(session),
                retrievals=SqlRagRetrievalRepository(session),
                embedder=create_embedding_provider(settings.embedding_provider),
                gateway=None,
            )
            top = await knowledge.retrieve(org.id, query)
            return {
                "query": query,
                "organization": org.name,
                "results": [
                    {
                        "document": item.document_title,
                        "version": item.document_version,
                        "score": round(item.score, 3),
                        "excerpt": item.chunk.content[:400],
                    }
                    for item in top
                ],
                "note": DISCLAIMER,
            }

    @server.tool(
        description=(
            "Operational counts for the organization: conversations, "
            "messages, risk signals, workflows by state, AI requests. "
            "Counts only, never content."
        )
    )
    async def get_platform_stats() -> dict[str, Any]:
        async with session_factory() as session:
            org = await _resolve_org(session, scoped_org)
            if org is None:
                return {"error": f"Organization '{scoped_org}' not found. Seed the database first."}
            stats: dict = {"organization": org.name}
            for key, query in _STAT_QUERIES.items():
                result = await session.execute(text(query), {"org": org.id})
                stats[key] = int(result.scalar_one())
            result = await session.execute(text(_WORKFLOWS_BY_STATE), {"org": org.id})
            stats["workflows"] = [
                {"type": row[0], "state": row[1], "count": int(row[2])} for row in result.all()
            ]
            stats["note"] = DISCLAIMER
            return stats

    return server


def main() -> None:
    import anyio

    from app.infrastructure.db import create_engine, create_session_factory

    engine = create_engine(get_settings().database_url)
    server = build_server(create_session_factory(engine))
    anyio.run(server.run_stdio_async)


if __name__ == "__main__":
    main()
