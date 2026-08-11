"""Periodic refresh of database backed gauges: workflow states, outbox lag,
and the review queue. Runs as a background task in the API lifespan."""

import asyncio

import structlog
from sqlalchemy import func, select

from app.infrastructure import metrics
from app.infrastructure.models import DomainEventLogRow, WorkflowInstanceRow

logger = structlog.get_logger()

REFRESH_SECONDS = 15.0


async def refresh_once(session_factory) -> None:
    async with session_factory() as session:
        workflow_counts = await session.execute(
            select(
                WorkflowInstanceRow.workflow_type,
                WorkflowInstanceRow.state,
                func.count(),
            ).group_by(WorkflowInstanceRow.workflow_type, WorkflowInstanceRow.state)
        )
        # Reset so states that empty out drop to zero instead of sticking.
        metrics.WORKFLOWS_BY_STATE.clear()
        pending_reviews = 0
        for workflow_type, state, count in workflow_counts:
            metrics.WORKFLOWS_BY_STATE.labels(workflow_type=workflow_type.value, state=state).set(
                count
            )
            if workflow_type.value == "risk_escalation" and state == "pending_review":
                pending_reviews = count
        metrics.REVIEW_QUEUE_DEPTH.set(pending_reviews)

        unpublished = await session.scalar(
            select(func.count())
            .select_from(DomainEventLogRow)
            .where(DomainEventLogRow.published_at.is_(None))
        )
        metrics.OUTBOX_UNPUBLISHED.set(unpublished or 0)


async def run_gauge_refresher(session_factory) -> None:
    while True:
        try:
            await refresh_once(session_factory)
        except Exception as exc:  # never let metrics kill the app
            logger.warning("gauge_refresh_failed", error_type=type(exc).__name__)
        await asyncio.sleep(REFRESH_SECONDS)
