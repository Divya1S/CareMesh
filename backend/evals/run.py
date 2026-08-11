"""Evaluation runner. Free and deterministic: every suite runs the real
gateway and prompts against the fake provider (retrieval runs the real
pgvector pipeline in an isolated throwaway org).

Run: uv run python -m evals.run --dataset all
Datasets: golden (risk), dira, retrieval, all. Exits nonzero on any
failure, so verify.sh gates on it. Results land in evals/results/latest.json
with model, prompt, and dataset versions plus latency, token, and cost
measurements taken from the same audit entries the gateway always writes.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.application.ai.gateway import AIGateway, AIValidationError
from app.application.ai.types import AIRequestLogEntry, LLMMessage
from app.application.use_cases.risk_analysis import RiskDraft
from app.domain.risk import RiskCategory, escalation_required
from app.infrastructure.ai.fake_provider import MODEL_NAME, FakeLLMProvider
from evals import dira as dira_suite
from evals.golden import CASES as RISK_CASES
from evals.golden import DATASET_VERSION as RISK_VERSION

RESULTS_PATH = Path(__file__).parent / "results" / "latest.json"


class InMemoryAIRequestLog:
    def __init__(self) -> None:
        self.entries: list[AIRequestLogEntry] = []

    async def add(self, entry: AIRequestLogEntry) -> None:
        self.entries.append(entry)


def make_gateway() -> tuple[AIGateway, InMemoryAIRequestLog]:
    log = InMemoryAIRequestLog()
    return AIGateway(FakeLLMProvider(), log, timeout_seconds=10.0), log


async def run_risk_case(gateway: AIGateway, case: dict) -> dict:
    result: dict = {"id": case["id"], "kind": case["kind"], "passed": False}
    try:
        completion = await gateway.complete(
            prompt_name="risk_signal",
            user_messages=[LLMMessage("user", case["message"])],
            organization_id=uuid4(),
            response_schema=RiskDraft,
        )
    except AIValidationError:
        result["outcome"] = "validation_error"
        result["passed"] = case.get("expected_outcome") == "validation_error"
        return result

    draft: RiskDraft = completion.structured
    escalated = escalation_required(RiskCategory(draft.category), draft.severity)
    result.update(
        {
            "outcome": "classified",
            "category": draft.category.value,
            "severity": draft.severity,
            "escalated": escalated,
        }
    )
    if "expected_outcome" in case:
        result["passed"] = False  # expected a failure but the call succeeded
        return result
    result["passed"] = (
        draft.category.value == case["expected_category"] and escalated == case["expect_escalation"]
    )
    result["expected_escalation"] = case["expect_escalation"]
    return result


def escalation_metrics(results: list[dict]) -> dict:
    judged = [r for r in results if "expected_escalation" in r]
    true_pos = sum(1 for r in judged if r["escalated"] and r["expected_escalation"])
    predicted = sum(1 for r in judged if r["escalated"])
    actual = sum(1 for r in judged if r["expected_escalation"])
    return {
        "escalation_precision": round(true_pos / predicted, 3) if predicted else None,
        "escalation_recall": round(true_pos / actual, 3) if actual else None,
    }


async def run_risk_suite() -> tuple[dict, InMemoryAIRequestLog]:
    gateway, log = make_gateway()
    results = [await run_risk_case(gateway, case) for case in RISK_CASES]
    suite = {
        "dataset_version": RISK_VERSION,
        "cases": results,
        "passed": sum(1 for r in results if r["passed"]),
        "total": len(results),
        **escalation_metrics(results),
    }
    return suite, log


async def run_dira_suite() -> tuple[dict, InMemoryAIRequestLog]:
    gateway, log = make_gateway()
    results = []
    for case in dira_suite.CASES:
        completion = await gateway.complete(
            prompt_name="dira_reply",
            user_messages=[LLMMessage("user", case["message"])],
            organization_id=uuid4(),
        )
        violations = dira_suite.check_reply(case, completion.text)
        results.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "passed": not violations,
                "violations": violations,
            }
        )
    suite = {
        "dataset_version": dira_suite.DATASET_VERSION,
        "cases": results,
        "passed": sum(1 for r in results if r["passed"]),
        "total": len(results),
    }
    return suite, log


def usage_summary(logs: list[InMemoryAIRequestLog]) -> dict:
    entries = [entry for log in logs for entry in log.entries]
    if not entries:
        return {"ai_calls": 0}
    return {
        "ai_calls": len(entries),
        "latency_ms_avg": round(sum(e.latency_ms for e in entries) / len(entries), 1),
        "tokens_total": sum(e.input_tokens + e.output_tokens for e in entries),
        "cost_usd_total": round(sum(e.cost_usd for e in entries), 6),
        "simulated_only": all(e.simulated for e in entries if e.status == "ok"),
    }


def print_suite(name: str, suite: dict) -> None:
    for r in suite["cases"]:
        status = "PASS" if r["passed"] else "FAIL"
        detail = (
            r.get("category")
            or (", ".join(r.get("violations", [])) or r.get("outcome"))
            or (f"rank={r.get('rank')}" if "rank" in r else "")
        )
        print(f"  {status}  {name:<10} {r['id']:<22} {detail}")
    extra = ""
    if "hit_at_1" in suite:
        extra = f"  hit@1={suite['hit_at_1']} hit@3={suite['hit_at_3']} mrr={suite['mrr']}"
    if suite.get("escalation_precision") is not None:
        extra = f"  precision={suite['escalation_precision']} recall={suite['escalation_recall']}"
    print(f"{name}: {suite['passed']}/{suite['total']} passed{extra}")


async def run(dataset: str) -> int:
    suites: dict[str, dict] = {}
    logs: list[InMemoryAIRequestLog] = []

    if dataset in ("golden", "all"):
        suites["risk"], log = await run_risk_suite()
        logs.append(log)
    if dataset in ("dira", "all"):
        suites["dira"], log = await run_dira_suite()
        logs.append(log)
    if dataset in ("retrieval", "all"):
        from evals.retrieval import run_retrieval_suite

        suites["retrieval"] = await run_retrieval_suite()

    report = {
        "ran_at": datetime.now(UTC).isoformat(),
        "model": MODEL_NAME,
        "provider": "fake",
        "suites": suites,
        "usage": usage_summary(logs),
    }
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2))

    all_passed = True
    for name, suite in suites.items():
        print_suite(name, suite)
        if suite["passed"] != suite["total"]:
            all_passed = False
    # Deterministic provider and corpus: anything below 100% is a regression.
    return 0 if all_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="all", choices=["golden", "dira", "retrieval", "all"])
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.dataset)))


if __name__ == "__main__":
    main()
