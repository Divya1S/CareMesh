"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  getMe,
  schoolReferrals,
  schoolRoster,
  submitReferral,
  type Me,
  type Referral,
  type RosterEntry,
} from "@/lib/api";
import { clearTokens, isLoggedIn } from "@/lib/auth";

/* Referral submission is a thread stepper (DESIGN.md 4.5): Student ->
   Concern -> Consent -> Submitted. Status chips mirror the backend state
   machine names exactly. */

const STEPS = ["Student", "Concern", "Consent", "Submitted"] as const;

function stateTone(state: string): "warn" | "ok" | "neutral" {
  if (state === "submitted") return "warn";
  if (state === "accepted") return "ok";
  return "neutral";
}

export default function SchoolPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [referrals, setReferrals] = useState<Referral[]>([]);
  const [step, setStep] = useState(0);
  const [patientId, setPatientId] = useState<string | null>(null);
  const [concern, setConcern] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    setReferrals(await schoolReferrals());
  }, []);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const profile = await getMe();
        if (profile.role !== "school_staff") {
          router.replace("/login");
          return;
        }
        setMe(profile);
        setRoster(await schoolRoster());
        await refresh();
      } catch {
        clearTokens();
        router.replace("/login");
      } finally {
        setLoaded(true);
      }
    })();
  }, [router, refresh]);

  async function onSubmit() {
    if (!patientId || !consent) return;
    setBusy(true);
    try {
      await submitReferral(patientId, concern.trim(), consent);
      setStep(3);
      setPatientId(null);
      setConcern("");
      setConsent(false);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  function signOut() {
    clearTokens();
    router.replace("/login");
  }

  if (!loaded) {
    return (
      <main className="grid min-h-[60vh] place-items-center text-ink-soft">
        <p>Loading the school dashboard…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-(family-name:--font-display) text-xl font-bold text-ink">
            School dashboard
          </h1>
          <p className="text-[0.8125rem] text-ink-soft">
            Refer a student to the care team. You will see the status of your
            referrals here; care details stay with the care team.
          </p>
        </div>
        <Button variant="ghost" onClick={signOut}>
          Sign out{me ? ` (${me.display_name})` : ""}
        </Button>
      </header>

      <section className="mb-8">
        <h2 className="mb-2 font-semibold text-ink">New referral</h2>
        <Card className="p-5">
          {/* The thread stepper */}
          <ol className="mb-5 flex items-center gap-2">
            {STEPS.map((label, index) => (
              <li key={label} className="flex items-center gap-2">
                <span
                  className={`grid h-6 w-6 place-items-center rounded-pill border text-[0.75rem] font-medium ${
                    index <= step
                      ? "border-primary bg-primary-soft text-primary-strong"
                      : "border-line bg-card text-ink-soft"
                  }`}
                >
                  {index + 1}
                </span>
                <span
                  className={`text-[0.8125rem] ${index <= step ? "text-ink" : "text-ink-soft"}`}
                >
                  {label}
                </span>
                {index < STEPS.length - 1 ? (
                  <span aria-hidden className="h-px w-6 bg-primary/40" />
                ) : null}
              </li>
            ))}
          </ol>

          {step === 0 ? (
            <div>
              <p className="mb-2 text-[0.875rem] text-ink-soft">
                Who is this about?
              </p>
              <div className="flex flex-wrap gap-2">
                {roster.map((entry) => (
                  <button
                    key={entry.patient_id}
                    onClick={() => {
                      setPatientId(entry.patient_id);
                      setStep(1);
                    }}
                    className={`rounded-control border px-4 py-2 ${
                      patientId === entry.patient_id
                        ? "border-primary bg-primary-soft"
                        : "border-line bg-card hover:bg-primary-soft/50"
                    }`}
                  >
                    {entry.name}
                  </button>
                ))}
              </div>
            </div>
          ) : step === 1 ? (
            <div>
              <label htmlFor="concern" className="mb-1 block text-[0.875rem] text-ink">
                What have you noticed? Stick to what you observed.
              </label>
              <textarea
                id="concern"
                value={concern}
                onChange={(e) => setConcern(e.target.value)}
                rows={4}
                className="w-full rounded-control border border-line bg-card px-3.5 py-2.5"
              />
              <div className="mt-3 flex gap-2">
                <Button
                  onClick={() => setStep(2)}
                  disabled={concern.trim().length < 10}
                >
                  Continue
                </Button>
                <Button variant="ghost" onClick={() => setStep(0)}>
                  Back
                </Button>
              </div>
            </div>
          ) : step === 2 ? (
            <div>
              <label className="flex items-start gap-3 text-[0.9375rem] text-ink">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="mt-1 h-5 w-5 accent-(--primary)"
                />
                I confirm the student or their guardian consents to this
                referral being shared with the care team.
              </label>
              <div className="mt-4 flex gap-2">
                <Button onClick={onSubmit} disabled={!consent || busy}>
                  Submit referral
                </Button>
                <Button variant="ghost" onClick={() => setStep(1)}>
                  Back
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <p className="font-medium text-ok">Referral submitted.</p>
              <p className="mt-1 text-[0.875rem] text-ink-soft">
                The care team will review it. You can follow the status below.
              </p>
              <Button variant="ghost" className="mt-3" onClick={() => setStep(0)}>
                Start another
              </Button>
            </div>
          )}
        </Card>
      </section>

      <section>
        <h2 className="mb-2 font-semibold text-ink">Your referrals</h2>
        {referrals.length === 0 ? (
          <EmptyState
            title="No referrals yet"
            hint="When you submit a referral, its status appears here."
          />
        ) : (
          <div className="flex flex-col gap-2">
            {referrals.map((r) => (
              <Card key={r.referral_id} className="flex items-center gap-3 px-4 py-3">
                <Chip tone={stateTone(r.state)}>{r.state}</Chip>
                <span className="font-medium text-ink">{r.patient_name}</span>
                <span className="ml-auto text-[0.75rem] text-ink-soft">
                  {new Date(r.created_at).toLocaleDateString()}
                </span>
              </Card>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
