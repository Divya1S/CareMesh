"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AIFrame } from "@/components/ui/AIFrame";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  askKnowledge,
  listKnowledgeDocuments,
  type KnowledgeAnswer,
  type KnowledgeDocument,
} from "@/lib/api";
import { isLoggedIn } from "@/lib/auth";

export default function ResourcesPage() {
  const router = useRouter();
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<KnowledgeAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        setDocuments(await listKnowledgeDocuments());
      } finally {
        setLoaded(true);
      }
    })();
  }, [router]);

  async function onAsk(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    try {
      setAnswer(await askKnowledge(question.trim()));
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) {
    return (
      <main className="grid min-h-[60vh] place-items-center text-ink-soft">
        <p>Loading resources…</p>
      </main>
    );
  }

  return (
    <main className="patient-surface mx-auto max-w-[720px] px-6 py-8">
      <header className="mb-6">
        <Link href="/chat" className="text-[0.875rem] font-medium text-primary">
          ← Back to chat
        </Link>
        <h1 className="mt-2 font-(family-name:--font-display) text-2xl font-bold text-ink">
          Resources
        </h1>
        <p className="text-ink-soft">
          A small library your care team keeps for you. Ask a question and the
          answer will come only from these documents, with its sources shown.
        </p>
      </header>

      <form onSubmit={onAsk} className="mb-6 flex items-end gap-2">
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <input
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask something, like: how do I sleep better before an exam?"
          className="min-h-11 flex-1 rounded-control border border-line bg-card px-3.5"
        />
        <Button type="submit" disabled={busy || !question.trim()}>
          {busy ? "Looking…" : "Ask"}
        </Button>
      </form>

      {answer ? (
        answer.grounded ? (
          <AIFrame
            model={answer.model ?? undefined}
            simulated={answer.simulated ?? false}
            className="mb-6"
          >
            <p className="whitespace-pre-wrap text-ink">{answer.answer}</p>
            <div className="mt-3 border-t border-ai/20 pt-2">
              <p className="mb-1 text-[0.75rem] font-medium text-ink-soft">
                Sources this answer drew from
              </p>
              <ul className="flex flex-col gap-1">
                {answer.citations.map((c) => (
                  <li key={c.chunk_id} className="text-[0.8125rem] text-ink-soft">
                    <span className="font-medium text-ink">
                      {c.document_title} (v{c.document_version})
                    </span>
                    {c.used ? " · cited" : " · retrieved, not cited"} ·{" "}
                    {c.snippet.slice(0, 90)}…
                  </li>
                ))}
              </ul>
            </div>
          </AIFrame>
        ) : (
          <Card className="mb-6 p-4 text-ink">
            {answer.answer}
          </Card>
        )
      ) : null}

      <h2 className="mb-2 font-semibold text-ink">In the library</h2>
      {documents.length === 0 ? (
        <EmptyState
          title="No resources yet"
          hint="Your care team has not added any documents to the library."
        />
      ) : (
        <div className="flex flex-col gap-2">
          {documents.map((d) => (
            <Card key={d.id} className="flex items-center justify-between px-4 py-3">
              <span className="font-medium text-ink">{d.title}</span>
              <span className="text-[0.75rem] text-ink-soft">version {d.version}</span>
            </Card>
          ))}
        </div>
      )}
    </main>
  );
}
