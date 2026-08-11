"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import {
  checkEligibility,
  getMe,
  listClaims,
  myPatients,
  resubmitClaim,
  submitClaim,
  type Claim,
  type EligibilityResult,
  type Me,
} from "@/lib/api";
import { clearTokens, isLoggedIn } from "@/lib/auth";

const mono = "font-(family-name:--font-mono) text-[0.75rem]";

function stateTone(state: string): "warn" | "ok" | "risk" | "neutral" {
  if (state === "submitted" || state === "resubmitted") return "warn";
  if (state === "approved") return "ok";
  if (state === "denied") return "risk";
  return "neutral";
}

export default function BillingPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [patients, setPatients] = useState<{ patient_id: string; name: string }[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [memberId, setMemberId] = useState("");
  const [eligibility, setEligibility] = useState<EligibilityResult | null>(null);
  const [patientId, setPatientId] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("120.00");
  const [resubmitNotes, setResubmitNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    setClaims(await listClaims());
  }, []);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const profile = await getMe();
        if (profile.role !== "therapist") {
          router.replace("/login");
          return;
        }
        setMe(profile);
        setPatients(await myPatients());
        await refresh();
      } catch {
        clearTokens();
        router.replace("/login");
      } finally {
        setLoaded(true);
      }
    })();
  }, [router, refresh]);

  async function onCheck(event: React.FormEvent) {
    event.preventDefault();
    if (!memberId.trim()) return;
    setBusy(true);
    try {
      setEligibility(await checkEligibility(memberId.trim()));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitClaim(event: React.FormEvent) {
    event.preventDefault();
    if (!eligibility?.eligible || !patientId) return;
    const cents = Math.round(parseFloat(amount) * 100);
    if (!Number.isFinite(cents) || cents <= 0) return;
    setBusy(true);
    try {
      await submitClaim(
        patientId,
        description.trim(),
        cents,
        eligibility.eligibility_check_id,
      );
      setDescription("");
      setEligibility(null);
      setMemberId("");
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function onResubmit(claim: Claim) {
    const note = resubmitNotes[claim.claim_id]?.trim();
    if (!note) return;
    await resubmitClaim(claim.claim_id, note);
    setResubmitNotes((prev) => ({ ...prev, [claim.claim_id]: "" }));
    await refresh();
  }

  if (!loaded) {
    return (
      <main className="grid min-h-[60vh] place-items-center text-ink-soft">
        <p>Loading billing…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-8 text-[0.9375rem]">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <Link href="/clinician" className="text-[0.875rem] font-medium text-primary">
            ← Back to workspace
          </Link>
          <h1 className="mt-1 font-(family-name:--font-display) text-xl font-bold text-ink">
            Billing
          </h1>
          <p className="text-[0.8125rem] text-ink-soft">
            Check coverage, submit claims, and rework denials. The external
            payer is a labeled simulation.
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={() => {
            clearTokens();
            router.replace("/login");
          }}
        >
          Sign out{me ? ` (${me.display_name})` : ""}
        </Button>
      </header>

      <section className="mb-8">
        <h2 className="mb-2 font-semibold text-ink">1. Check eligibility</h2>
        <Card className="p-4">
          <form onSubmit={onCheck} className="flex items-end gap-2">
            <label className="flex-1 text-[0.8125rem] text-ink">
              Member id
              <input
                value={memberId}
                onChange={(e) => setMemberId(e.target.value)}
                placeholder="EVG-1001"
                className={`mt-1 block min-h-11 w-full rounded-control border border-line bg-card px-3 ${mono}`}
              />
            </label>
            <Button type="submit" disabled={busy || !memberId.trim()}>
              Check coverage
            </Button>
          </form>
          {eligibility ? (
            <p className="mt-3 flex items-center gap-2">
              <Chip tone={eligibility.eligible ? "ok" : "risk"}>
                {eligibility.eligible ? "eligible" : "not eligible"}
              </Chip>
              {eligibility.eligible ? (
                <span className="text-ink">{eligibility.plan_name}</span>
              ) : (
                <span className="text-ink-soft">
                  This member has no active coverage.
                </span>
              )}
              {eligibility.simulated ? (
                <Chip tone="neutral" title={`Adapter: ${eligibility.adapter}`}>
                  SIMULATED PAYER
                </Chip>
              ) : null}
            </p>
          ) : null}
        </Card>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 font-semibold text-ink">2. Submit a claim</h2>
        <Card className="p-4">
          <form onSubmit={onSubmitClaim} className="flex flex-wrap items-end gap-3">
            <label className="text-[0.8125rem] text-ink">
              Patient
              <select
                value={patientId}
                onChange={(e) => setPatientId(e.target.value)}
                className="mt-1 block min-h-11 rounded-control border border-line bg-card px-2"
              >
                <option value="">Choose…</option>
                {patients.map((p) => (
                  <option key={p.patient_id} value={p.patient_id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex-1 text-[0.8125rem] text-ink">
              Service description
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Therapy session, 50 minutes"
                className="mt-1 block min-h-11 w-full rounded-control border border-line bg-card px-3"
              />
            </label>
            <label className="text-[0.8125rem] text-ink">
              Amount ($)
              <input
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className={`mt-1 block min-h-11 w-28 rounded-control border border-line bg-card px-3 ${mono}`}
              />
            </label>
            <Button
              type="submit"
              disabled={
                busy || !eligibility?.eligible || !patientId || description.trim().length < 5
              }
            >
              Submit claim
            </Button>
          </form>
          {!eligibility?.eligible ? (
            <p className="mt-2 text-[0.8125rem] text-ink-soft">
              A passing eligibility check is required before submitting.
            </p>
          ) : null}
        </Card>
      </section>

      <section>
        <h2 className="mb-2 font-semibold text-ink">Your claims</h2>
        {claims.length === 0 ? (
          <p className="text-[0.875rem] text-ink-soft">No claims yet.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {claims.map((c) => (
              <Card key={c.claim_id} className="p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <Chip tone={stateTone(c.state)}>{c.state}</Chip>
                  <span className="font-medium text-ink">{c.patient_name}</span>
                  <span className="text-ink-soft">{c.description}</span>
                  <span className={`ml-auto ${mono} text-ink`}>
                    ${(c.amount_cents / 100).toFixed(2)}
                  </span>
                </div>
                {c.state === "denied" ? (
                  <div className="mt-3">
                    <p className="text-[0.8125rem] text-risk">
                      Denied: {c.denial_reason}
                    </p>
                    <div className="mt-2 flex items-end gap-2">
                      <input
                        value={resubmitNotes[c.claim_id] ?? ""}
                        onChange={(e) =>
                          setResubmitNotes((prev) => ({
                            ...prev,
                            [c.claim_id]: e.target.value,
                          }))
                        }
                        placeholder="What did you correct?"
                        className="min-h-11 flex-1 rounded-control border border-line bg-card px-3"
                      />
                      <Button
                        variant="ghost"
                        disabled={!(resubmitNotes[c.claim_id] ?? "").trim()}
                        onClick={() => onResubmit(c)}
                      >
                        Resubmit
                      </Button>
                    </div>
                  </div>
                ) : null}
              </Card>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
