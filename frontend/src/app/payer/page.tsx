"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import {
  claimHistory,
  decideClaim,
  getMe,
  listClaims,
  type Claim,
  type ClaimTransition,
  type Me,
} from "@/lib/api";
import { clearTokens, isLoggedIn } from "@/lib/auth";

/* State machine UI (DESIGN.md 4.6): a claims table in mono with an
   expandable state history rail per claim; denial tracking is a filtered
   view, not a separate page. */

const mono = "font-(family-name:--font-mono) text-[0.75rem]";

function stateTone(state: string): "warn" | "ok" | "risk" | "neutral" {
  if (state === "submitted" || state === "resubmitted") return "warn";
  if (state === "approved") return "ok";
  if (state === "denied") return "risk";
  return "neutral";
}

export default function PayerPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [deniedOnly, setDeniedOnly] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [history, setHistory] = useState<ClaimTransition[]>([]);
  const [denyReason, setDenyReason] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    setClaims(await listClaims());
    setExpanded(null);
  }, []);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const profile = await getMe();
        if (profile.role !== "payer_staff") {
          router.replace("/login");
          return;
        }
        setMe(profile);
        await refresh();
      } catch {
        clearTokens();
        router.replace("/login");
      } finally {
        setLoaded(true);
      }
    })();
  }, [router, refresh]);

  async function toggleHistory(claim: Claim) {
    if (expanded === claim.claim_id) {
      setExpanded(null);
      return;
    }
    setHistory(await claimHistory(claim.claim_id));
    setExpanded(claim.claim_id);
  }

  async function decide(claim: Claim, approve: boolean) {
    await decideClaim(
      claim.claim_id,
      approve,
      approve ? undefined : denyReason[claim.claim_id]?.trim(),
    );
    await refresh();
  }

  if (!loaded) {
    return (
      <main className="grid min-h-[60vh] place-items-center text-ink-soft">
        <p>Loading claims…</p>
      </main>
    );
  }

  const visible = deniedOnly ? claims.filter((c) => c.state === "denied") : claims;
  const reviewable = (c: Claim) => c.state === "submitted" || c.state === "resubmitted";

  return (
    <main className="mx-auto max-w-4xl px-6 py-8 text-[0.875rem]">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-(family-name:--font-display) text-xl font-bold text-ink">
            Claims review
          </h1>
          <p className="text-[0.8125rem] text-ink-soft">
            Every state change is a workflow transition, actor attributed and
            inspectable below.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => setDeniedOnly((v) => !v)}>
            {deniedOnly ? "Show all" : "Denied only"}
          </Button>
          <Button variant="ghost" onClick={refresh}>
            Refresh
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              clearTokens();
              router.replace("/login");
            }}
          >
            Sign out{me ? ` (${me.display_name})` : ""}
          </Button>
        </div>
      </header>

      <Card className="divide-y divide-line overflow-x-auto">
        {visible.length === 0 ? (
          <p className="p-4 text-ink-soft">
            {deniedOnly ? "No denied claims." : "No claims yet."}
          </p>
        ) : (
          visible.map((c) => (
            <div key={c.claim_id} className="p-3">
              <div className="flex flex-wrap items-center gap-3">
                <Chip tone={stateTone(c.state)}>{c.state}</Chip>
                <span className="font-medium text-ink">{c.patient_name}</span>
                <span className="text-ink-soft">{c.description}</span>
                <span className={`${mono} text-ink-soft`}>{c.member_id}</span>
                <span className={`${mono} ml-auto text-ink`}>
                  ${(c.amount_cents / 100).toFixed(2)}
                </span>
                <button
                  onClick={() => toggleHistory(c)}
                  className="text-[0.8125rem] font-medium text-primary"
                >
                  {expanded === c.claim_id ? "Hide history" : "History"}
                </button>
              </div>

              {c.state === "denied" && c.denial_reason ? (
                <p className="mt-1 text-[0.8125rem] text-risk">
                  Denied: {c.denial_reason}
                </p>
              ) : null}
              {c.resubmit_note ? (
                <p className="mt-1 text-[0.8125rem] text-ink-soft">
                  Resubmission note: {c.resubmit_note}
                </p>
              ) : null}

              {reviewable(c) ? (
                <div className="mt-2 flex flex-wrap items-end gap-2">
                  <Button onClick={() => decide(c, true)}>Approve</Button>
                  <input
                    value={denyReason[c.claim_id] ?? ""}
                    onChange={(e) =>
                      setDenyReason((prev) => ({
                        ...prev,
                        [c.claim_id]: e.target.value,
                      }))
                    }
                    placeholder="Denial reason (required to deny)"
                    className="min-h-11 flex-1 rounded-control border border-line bg-card px-3"
                  />
                  <Button
                    variant="destructive"
                    disabled={!(denyReason[c.claim_id] ?? "").trim()}
                    onClick={() => decide(c, false)}
                  >
                    Deny
                  </Button>
                </div>
              ) : null}

              {expanded === c.claim_id ? (
                <ul className="mt-2 border-l-2 border-primary-soft pl-4">
                  {history.map((t, i) => (
                    <li key={i} className="py-1">
                      <span className={mono}>
                        {t.from_state ?? "∅"} → {t.to_state}
                      </span>{" "}
                      <span className="text-ink-soft">
                        {t.reason} ·{" "}
                        {new Date(t.occurred_at).toLocaleString([], {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))
        )}
      </Card>
    </main>
  );
}
