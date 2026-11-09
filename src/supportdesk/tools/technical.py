"""Technical tools: search_knowledge_base, get_service_status, create_bug_ticket."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..repositories import Repositories
from ..schemas import CreateBugTicketArgs, GetServiceStatusArgs, SearchKBArgs
from .base import ToolContext, execute


def make_technical_tools(context: ToolContext) -> dict[str, Any]:
    @tool(args_schema=SearchKBArgs)
    def search_knowledge_base(query: str) -> str:
        """Search the help knowledge base. Returns article snippets (with a note
        when an article is outdated) so answers can be cited."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            articles = repos.articles.search(args["query"], limit=3)
            if not articles:
                return "No knowledge-base articles matched your query."
            parts = []
            for a in articles:
                flag = " [OUTDATED]" if a.is_outdated else ""
                parts.append(f"- {a.title}{flag}: {a.content[:160]}")
            return "\n".join(parts)

        return execute(context, "technical", "search_knowledge_base", {"query": query}, _run)

    @tool(args_schema=GetServiceStatusArgs)
    def get_service_status() -> str:
        """Current service-health status (healthy / degraded / outage)."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            status = repos.incidents.get_status().value
            return f"Service status: {status}."

        return execute(context, "technical", "get_service_status", {}, _run)

    @tool(args_schema=CreateBugTicketArgs)
    def create_bug_ticket(title: str, description: str) -> str:
        """File a bug ticket for the engineering team."""

        def _run(ctx: ToolContext, repos: Repositories, args: dict[str, Any]) -> str:
            ticket = repos.tickets.create(
                ctx.customer_id, args["title"], args["description"], specialist="technical"
            )
            return f"Bug ticket #{ticket.id} created: {ticket.subject}."

        return execute(
            context,
            "technical",
            "create_bug_ticket",
            {"title": title, "description": description},
            _run,
        )

    return {
        "search_knowledge_base": search_knowledge_base,
        "get_service_status": get_service_status,
        "create_bug_ticket": create_bug_ticket,
    }
