"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AIFrame } from "@/components/ui/AIFrame";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { EmptyState } from "@/components/ui/EmptyState";
import { SeverityLabel } from "@/components/ui/SeverityLabel";
import {
  acknowledgeAppointment,
  decideReferral,
  decideReview,
  getMe,
  listAppointments,
  listReviews,
  pendingReferrals,
  shareGuardianUpdate,
  type Me,
  type Referral,
  type ReviewDecision,
  type ReviewItem,
  myPatients,
} from "@/lib/api";
import { clearTokens, isLoggedIn } from "@/lib/auth";

type Decided = { decision: ReviewDecision };

export default function ClinicianPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [referrals, setReferrals] = useState<Referral[]>([]);
  const [appointments, setAppointments] = useState<
    { request_id: string; patient_name: string; note: string; created_at: string }[]
  >([]);
  const [patients, setPatients] = useState<{ patient_id: string; name: string }[]>([]);
  const [updatePatient, setUpdatePatient] = useState("");
  const [updateText, setUpdateText] = useState("");
  const [updateSent, setUpdateSent] = useState(false);
  const [decided, setDecided] = useState<Record<string, Decided>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [severityOverride, setSeverityOverride] = useState(1);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    const [reviews, pending, assigned, requests] = await Promise.all([
      listReviews(),
      pendingReferrals(),
      myPatients(),
      listAppointments(),
    ]);
    setItems(reviews);
    setReferrals(pending);
    setPatients(assigned);
    setAppointments(requests);
    setDecided({});
    setEditing(null);
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
          router.replace("/chat");
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

  async function onReferral(referral: Referral, accept: boolean) {
    await decideReferral(referral.referral_id, accept);
    await refresh();
  }

  async function onShareUpdate(event: React.FormEvent) {
    event.preventDefault();
    if (!updatePatient || updateText.trim().length < 5) return;
    await shareGuardianUpdate(updatePatient, updateText.trim());
    setUpdateText("");
    setUpdateSent(true);
  }

  async function decide(item: ReviewItem, decision: ReviewDecision) {
    setBusy(item.workflow_id);
    try {
      await decideReview(
        item.workflow_id,
        decision,
        decision === "edit" ? severityOverride : undefined,
        decision === "edit" ? note : undefined,
      );
      setDecided((prev) => ({ ...prev, [item.workflow_id]: { decision } }));
      setEditing(null);
      setNote("");
    } finally {
      setBusy(null);
    }
  }

  function signOut() {
    clearTokens();
    router.replace("/login");
  }

  if (!loaded) {
    return (
      <main className="grid min-h-[60vh] place-items-center text-ink-soft">
        <p>Loading the review queue…</p>
      </main>
    );
  }

  const open = items.filter((i) => !decided[i.workflow_id]);

  return (
    <main className="mx-auto max-w-3xl px-6 py-8 text-[0.9375rem]">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-(family-name:--font-display) text-xl font-bold text-ink">
            Risk review queue
          </h1>
          <p className="text-[0.8125rem] text-ink-soft">
            AI detected signals for your assigned patients. Nothing here is a
            diagnosis; your decision is what counts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => router.push("/billing")}>
            Billing
          </Button>
          <Button variant="ghost" onClick={refresh}>
            Refresh
          </Button>
          <Button variant="ghost" onClick={signOut}>
            Sign out{me ? ` (${me.display_name})` : ""}
          </Button>
        </div>
      </header>

      {items.length === 0 ? (
        <EmptyState
          title="No signals waiting for review"
          hint="When Dira's risk analysis flags a message from one of your patients, it appears here."
        />
      ) : (
        <div className="flex flex-col gap-4">
          {items.map((item) => {
            const done = decided[item.workflow_id];
            return (
              <div key={item.workflow_id}>
                {done ? (
                  <div className="rounded-card border-l-[3px] border-primary bg-card p-4 shadow-soft">
                    <Chip tone="primary">
                      {done.decision === "accept"
                        ? "Accepted"
                        : done.decision === "edit"
                          ? "Edited"
                          : "Rejected"}{" "}
                      by {me?.display_name}
                    </Chip>
                    <p className="mt-2 text-ink-soft">
                      Recorded. The workflow is resolved and the decision is
                      audited.
                    </p>
                  </div>
                ) : (
                  <AIFrame
                    model={item.model}
                    promptVersion={`risk_signal v${item.prompt_version}`}
                    simulated={item.simulated}
                  >
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <SeverityLabel severity={item.severity} />
                      <span className="text-[0.75rem] text-ink-soft">
                        {item.category} · confidence{" "}
                        {Math.round(item.confidence * 100)}%
                      </span>
                    </div>
                    <p className="font-medium text-ink">{item.patient_name}</p>
                    <blockquote className="mt-1 border-l-2 border-line pl-3 text-ink">
                      {item.message_content}
                    </blockquote>
                    <p className="mt-2 text-[0.8125rem] text-ink-soft">
                      Evidence noticed: “{item.evidence}”
                    </p>

                    {editing === item.workflow_id ? (
                      <div className="mt-3 flex flex-wrap items-end gap-3">
                        <label className="text-[0.8125rem] text-ink">
                          Corrected severity
                          <select
                            value={severityOverride}
                            onChange={(e) => setSeverityOverride(Number(e.target.value))}
                            className="mt-1 block min-h-11 rounded-control border border-line bg-card px-2"
                          >
                            {[0, 1, 2, 3].map((s) => (
                              <option key={s} value={s}>
                                {s}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="flex-1 text-[0.8125rem] text-ink">
                          Note
                          <input
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                            placeholder="Why the correction?"
                            className="mt-1 block min-h-11 w-full rounded-control border border-line bg-card px-3"
                          />
                        </label>
                        <Button
                          disabled={busy === item.workflow_id}
                          onClick={() => decide(item, "edit")}
                        >
                          Save correction
                        </Button>
                        <Button variant="ghost" onClick={() => setEditing(null)}>
                          Cancel
                        </Button>
                      </div>
                    ) : (
                      <div className="mt-3 flex gap-2">
                        <Button
                          disabled={busy === item.workflow_id}
                          onClick={() => decide(item, "accept")}
                        >
                          Accept signal
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => setEditing(item.workflow_id)}
                        >
                          Edit severity
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={busy === item.workflow_id}
                          onClick={() => decide(item, "reject")}
                        >
                          Reject signal
                        </Button>
                      </div>
                    )}
                  </AIFrame>
                )}
              </div>
            );
          })}
          {open.length === 0 && items.length > 0 ? (
            <p className="text-center text-[0.875rem] text-ink-soft">
              Queue clear. Refresh to check for new signals.
            </p>
          ) : null}
        </div>
      )}

      <section className="mt-10">
        <h2 className="mb-2 font-semibold text-ink">Appointment requests</h2>
        {appointments.length === 0 ? (
          <p className="text-[0.875rem] text-ink-soft">
            None waiting. Requests made through Dira appear here.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {appointments.map((a) => (
              <div
                key={a.request_id}
                className="flex flex-wrap items-center gap-3 rounded-card border border-line bg-card p-4 shadow-soft"
              >
                <Chip tone="warn">requested</Chip>
                <span className="font-medium text-ink">{a.patient_name}</span>
                <span className="text-[0.875rem] text-ink-soft">{a.note}</span>
                <Button
                  className="ml-auto"
                  variant="ghost"
                  onClick={async () => {
                    await acknowledgeAppointment(a.request_id);
                    await refresh();
                  }}
                >
                  Acknowledge
                </Button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mt-10">
        <h2 className="mb-2 font-semibold text-ink">School referrals</h2>
        {referrals.length === 0 ? (
          <p className="text-[0.875rem] text-ink-soft">
            No referrals waiting. School submissions appear here.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            {referrals.map((r) => (
              <div
                key={r.referral_id}
                className="rounded-card border border-line bg-card p-4 shadow-soft"
              >
                <div className="mb-1 flex items-center gap-2">
                  <Chip tone="warn">{r.state}</Chip>
                  <span className="font-medium text-ink">{r.patient_name}</span>
                  <span className="ml-auto text-[0.75rem] text-ink-soft">
                    {new Date(r.created_at).toLocaleDateString()}
                  </span>
                </div>
                <p className="text-[0.9375rem] text-ink">{r.concern}</p>
                <div className="mt-3 flex gap-2">
                  <Button onClick={() => onReferral(r, true)}>
                    Accept and take on
                  </Button>
                  <Button variant="ghost" onClick={() => onReferral(r, false)}>
                    Decline
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mt-10">
        <h2 className="mb-2 font-semibold text-ink">Share an update with a guardian</h2>
        <form
          onSubmit={onShareUpdate}
          className="rounded-card border border-line bg-card p-4 shadow-soft"
        >
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-[0.8125rem] text-ink">
              Patient
              <select
                value={updatePatient}
                onChange={(e) => setUpdatePatient(e.target.value)}
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
              Update, written for the guardian
              <input
                value={updateText}
                onChange={(e) => {
                  setUpdateText(e.target.value);
                  setUpdateSent(false);
                }}
                placeholder="What should the guardian know?"
                className="mt-1 block min-h-11 w-full rounded-control border border-line bg-card px-3"
              />
            </label>
            <Button
              type="submit"
              disabled={!updatePatient || updateText.trim().length < 5}
            >
              Share update
            </Button>
          </div>
          {updateSent ? (
            <p className="mt-2 text-[0.8125rem] text-ok">
              Update shared. Linked guardians were notified.
            </p>
          ) : null}
        </form>
      </section>
    </main>
  );
}
