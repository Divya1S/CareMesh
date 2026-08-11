# SIMULATED
"""The fake external payer adapter.

Real payer integrations (X12 270/271 eligibility, clearinghouses) sit
behind this interface in a real deployment. This adapter is a labeled
simulation with deterministic behavior so the billing workflow around it is
fully testable: member ids containing INELIG are ineligible, everyone else
is covered. Every result carries simulated=True and the adapter name, and
both are stored with the eligibility check.
Replacement path: implement the PayerAdapter protocol against a real
clearinghouse and select it in configuration.
"""

from dataclasses import dataclass
from typing import Protocol

ADAPTER_NAME = "fake-payer-1"


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    plan_name: str
    adapter: str
    simulated: bool


class PayerAdapter(Protocol):
    name: str

    def check_eligibility(self, member_id: str) -> EligibilityResult: ...


class FakePayerAdapter:
    name = ADAPTER_NAME

    def check_eligibility(self, member_id: str) -> EligibilityResult:
        normalized = member_id.strip().upper()
        if "INELIG" in normalized:
            return EligibilityResult(
                eligible=False, plan_name="", adapter=self.name, simulated=True
            )
        plan = "Horizon Care Plus" if normalized[:1] in "AEIOU" else "Horizon Care Basic"
        return EligibilityResult(eligible=True, plan_name=plan, adapter=self.name, simulated=True)
