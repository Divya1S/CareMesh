"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import {
  getMe,
  opsAIRequestDetail,
  opsListAIRequests,
  opsListEvents,
  opsListWorkflows,
  opsRepublishEvent,
  opsViewDlq,
  opsWorkflowDetail,
  type Me,
  type OpsAIRequest,
  type OpsAIRequestDetail,
  type OpsDlq,
  type OpsEvent,
  type OpsWorkflow,
  type OpsWorkflowDetail,
} from "@/lib/api";
import { clearTokens, isLoggedIn } from "@/lib/auth";

/* The engineering control plane (DESIGN.md 4.7): dense, mono for ids,
   powerful rather than soft. Same tokens as everywhere else. */

const mono = "font-(family-name:--font-mono) text-[0.75rem]";

function stateTone(state: string): "warn" | "ok" | "risk" {
  if (state === "pending_review") return "warn";
  if (state === "resolved") return "ok";
  return "risk";
}

function when(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function OpsPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [workflows, setWorkflows] = useState<OpsWorkflow[]>([]);
  const [workflowDetail, setWorkflowDetail] = useState<OpsWorkflowDetail | null>(null);
  const [aiRequests, setAIRequests] = useState<OpsAIRequest[]>([]);
  const [aiDetail, setAIDetail] = useState<OpsAIRequestDetail | null>(null);
  const [events, setEvents] = useState<OpsEvent[]>([]);
  const [dlq, setDlq] = useState<OpsDlq | null>(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    const [w, a, e, d] = await Promise.all([
      opsListWorkflows(),
      opsListAIRequests(),
      opsListEvents(),
      opsViewDlq(),
    ]);
    setWorkflows(w);
    setAIRequests(a);
    setEvents(e);
    setDlq(d);
  }, []);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const profile = await getMe();
        if (profile.role !== "ops_admin") {
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

  async function republish(eventId: string) {
    if (
      !window.confirm(
        "Republish this event? Consumers are idempotent by event id, so a " +
          "replay is safe: already processed effects are skipped.",
      )
    ) {
      return;
    }
    await opsRepublishEvent(eventId);
    await refresh();
  }

  function signOut() {
    clearTokens();
    router.replace("/login");
  }

  if (!loaded) {
    return (
      <main className="grid min-h-[60vh] place-items-center text-ink-soft">
        <p>Loading the control plane…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-8 text-[0.875rem]">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-(family-name:--font-display) text-xl font-bold text-ink">
            Operations console
          </h1>
          <p className="text-[0.8125rem] text-ink-soft">
            Workflows, AI requests, the event outbox, and dead letters.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={refresh}>
            Refresh
          </Button>
          <Button variant="ghost" onClick={signOut}>
            Sign out{me ? ` (${me.display_name})` : ""}
          </Button>
        </div>
      </header>

      <section className="mb-8">
        <h2 className="mb-2 font-semibold text-ink">Workflows</h2>
        <Card className="divide-y divide-line overflow-x-auto">
          {workflows.length === 0 ? (
            <p className="p-4 text-ink-soft">No workflows yet.</p>
          ) : (
            workflows.map((w) => (
              <div key={w.id} className="p-3">
                <button
                  className="flex w-full flex-wrap items-center gap-3 text-left"
                  onClick={async () =>
                    setWorkflowDetail(
                      workflowDetail?.workflow.id === w.id
                        ? null
                        : await opsWorkflowDetail(w.id),
                    )
                  }
                >
                  <Chip tone={stateTone(w.state)}>{w.state}</Chip>
                  <span className="font-medium">{w.workflow_type}</span>
                  <span className={`${mono} text-ink-soft`}>{w.id}</span>
                  <span className="ml-auto text-ink-soft">{when(w.updated_at)}</span>
                </button>
                {workflowDetail?.workflow.id === w.id ? (
                  <ul className="mt-2 border-l-2 border-primary-soft pl-4">
                    {workflowDetail.transitions.map((t, i) => (
                      <li key={i} className="py-1">
                        <span className={mono}>
                          {t.from_state ?? "∅"} → {t.to_state}
                        </span>{" "}
                        <span className="text-ink-soft">
                          by {t.actor} · {t.reason} · {when(t.occurred_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))
          )}
        </Card>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 font-semibold text-ink">AI requests</h2>
        <Card className="divide-y divide-line overflow-x-auto">
          {aiRequests.length === 0 ? (
            <p className="p-4 text-ink-soft">No AI requests yet.</p>
          ) : (
            aiRequests.map((r) => (
              <div key={r.id} className="p-3">
                <button
                  className="flex w-full flex-wrap items-center gap-3 text-left"
                  onClick={async () =>
                    setAIDetail(aiDetail?.id === r.id ? null : await opsAIRequestDetail(r.id))
                  }
                >
                  <Chip tone={r.status === "ok" ? "ok" : "risk"}>{r.status}</Chip>
                  {r.simulated ? <Chip tone="ai">SIMULATED</Chip> : null}
                  <span className="font-medium">
                    {r.prompt_name} v{r.prompt_version}
                  </span>
                  <span className="text-ink-soft">{r.model}</span>
                  <span className={`${mono} text-ink-soft`}>
                    {r.input_tokens}/{r.output_tokens} tok · ${r.cost_usd.toFixed(4)} ·{" "}
                    {r.latency_ms}ms
                  </span>
                  <span className="ml-auto text-ink-soft">{when(r.created_at)}</span>
                </button>
                {aiDetail?.id === r.id ? (
                  <div className={`mt-2 rounded-control bg-surface p-3 ${mono}`}>
                    <p className="mb-1 text-ink-soft">request:</p>
                    <pre className="max-h-40 overflow-auto whitespace-pre-wrap">
                      {JSON.stringify(aiDetail.request_messages, null, 2)}
                    </pre>
                    <p className="mt-2 mb-1 text-ink-soft">response:</p>
                    <pre className="max-h-40 overflow-auto whitespace-pre-wrap">
                      {aiDetail.response_text ?? "(none)"}
                    </pre>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </Card>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 font-semibold text-ink">Event outbox</h2>
        <Card className="divide-y divide-line overflow-x-auto">
          {events.map((e) => (
            <div key={e.id} className="flex flex-wrap items-center gap-3 p-3">
              <Chip tone={e.published_at ? "ok" : "warn"}>
                {e.published_at ? "published" : "pending"}
              </Chip>
              <span className="font-medium">
                {e.event_type} v{e.schema_version}
              </span>
              <span className={`${mono} text-ink-soft`}>{e.correlation_id}</span>
              <span className="ml-auto flex items-center gap-2">
                <span className="text-ink-soft">{when(e.occurred_at)}</span>
                {e.published_at ? (
                  <Button variant="ghost" onClick={() => republish(e.id)}>
                    Republish
                  </Button>
                ) : null}
              </span>
            </div>
          ))}
        </Card>
      </section>

      <section>
        <h2 className="mb-2 font-semibold text-ink">Dead letters</h2>
        <Card className="p-4">
          <p className={`${mono} mb-2 text-ink-soft`}>{dlq?.topic}</p>
          {dlq && dlq.records.length > 0 ? (
            <ul className={`${mono} flex flex-col gap-1`}>
              {dlq.records.map((r, i) => (
                <li key={i} className="truncate rounded-control bg-surface px-2 py-1">
                  {r}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-ink-soft">
              No dead letters. Poison messages land here after bounded retries.
            </p>
          )}
        </Card>
      </section>
    </main>
  );
}
