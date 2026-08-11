"""Evaluation runner. Free and deterministic: the golden dataset runs the
real gateway and the real risk_signal prompt against the fake provider.

Run: uv run python -m evals.run --dataset golden
Exits nonzero on any failure, so verify.sh gates on it. Results are written
to evals/results/latest.json with model, prompt, and dataset versions.
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
from evals.golden import CASES, DATASET_VERSION

RESULTS_PATH = Path(__file__).parent / "results" / "latest.json"


class InMemoryAIRequestLog:
    def __init__(self) -> None:
        self.entries: list[AIRequestLogEntry] = []

    async def add(self, entry: AIRequestLogEntry) -> None:
        self.entries.append(entry)


async def run_case(gateway: AIGateway, case: dict) -> dict:
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
    return result


async def run_dataset() -> int:
    log = InMemoryAIRequestLog()
    gateway = AIGateway(FakeLLMProvider(), log, timeout_seconds=10.0)
    results = [await run_case(gateway, case) for case in CASES]
    passed = sum(1 for r in results if r["passed"])

    report = {
        "dataset_version": DATASET_VERSION,
        "model": MODEL_NAME,
        "provider": "fake",
        "prompt": "risk_signal v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "total": len(results),
        "passed": passed,
        "cases": results,
    }
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2))

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        detail = r.get("category", r.get("outcome", ""))
        print(f"  {status}  {r['id']:<20} {r['kind']:<10} {detail}")
    print(f"evals: {passed}/{len(results)} passed ({DATASET_VERSION}, {MODEL_NAME})")
    # Deterministic provider: anything below 100 percent is a regression.
    return 0 if passed == len(results) else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="golden", choices=["golden"])
    parser.parse_args()
    sys.exit(asyncio.run(run_dataset()))


if __name__ == "__main__":
    main()
