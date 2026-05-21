# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Eval-related background jobs."""

import structlog

logger = structlog.get_logger(__name__)


async def run_eval(ctx: dict, agent_id: str, trace_id: str | None = None, project_id: str = "default"):
    """Background job: run eval on an agent's traces."""
    logger.info("eval_started", agent_id=agent_id, trace_id=trace_id, project_id=project_id)
    try:
        from services.clickhouse import query_traces
        from services.eval.eval_engine import run_eval_on_trace
        from services.redis import publish

        if trace_id:
            scores = await run_eval_on_trace(agent_id, trace_id, project_id=project_id)
            await publish(
                f"eval:{agent_id}",
                {
                    "agent_id": agent_id,
                    "trace_id": trace_id,
                    "scores_written": len(scores),
                },
            )
        else:
            traces = await query_traces(project_id, agent_id=agent_id, limit=20)
            for t in traces:
                tid = t.get("trace_id", "")
                scores = await run_eval_on_trace(agent_id, tid, project_id=project_id)
                await publish(
                    f"eval:{agent_id}",
                    {
                        "agent_id": agent_id,
                        "trace_id": tid,
                        "scores_written": len(scores),
                    },
                )
    except Exception as e:
        logger.exception("eval_failed", error=str(e))
