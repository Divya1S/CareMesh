"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { ChatBubble, type BubbleSender } from "@/components/ui/ChatBubble";
import { Chip } from "@/components/ui/Chip";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  createConversation,
  getMe,
  listConversations,
  listMessages,
  streamMessage,
  type Conversation,
  type Me,
  type Message,
} from "@/lib/api";
import { clearTokens, isLoggedIn } from "@/lib/auth";

const NAV_ITEMS = ["Home", "Chat", "Appointments", "My care team", "Resources"];

function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function ChatPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [toolLines, setToolLines] = useState<string[]>([]);
  const [streamingActive, setStreamingActive] = useState(false);
  // Provenance of the in flight stream, from the stream's start event.
  // Defaults to true: wrongly labeling real output SIMULATED is the safe
  // direction; the badge is never asserted from nothing.
  const [streamSimulated, setStreamSimulated] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const refreshMessages = useCallback(async (conversationId: string) => {
    setMessages(await listMessages(conversationId));
  }, []);

  const selectConversation = useCallback(
    (conversationId: string) => {
      setSelectedId(conversationId);
      setMessages([]);
      void refreshMessages(conversationId);
    },
    [refreshMessages],
  );

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const [profile, convs] = await Promise.all([getMe(), listConversations()]);
        setMe(profile);
        setConversations(convs);
        if (convs.length > 0) selectConversation(convs[0].id);
      } catch {
        clearTokens();
        router.replace("/login");
      } finally {
        setLoaded(true);
      }
    })();
  }, [router, selectConversation]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, streamText]);

  async function onStartConversation(event: React.FormEvent) {
    event.preventDefault();
    if (!newTitle.trim()) return;
    const conversation = await createConversation(newTitle.trim());
    setNewTitle("");
    setConversations((prev) => [conversation, ...prev]);
    selectConversation(conversation.id);
  }

  async function onSend(event: React.FormEvent) {
    event.preventDefault();
    if (!draft.trim() || !selectedId) return;
    setBusy(true);
    setStreamText("");
    setToolLines([]);
    setStreamSimulated(true);
    setStreamingActive(true);
    try {
      await streamMessage(selectedId, draft.trim(), (streamEvent) => {
        if (streamEvent.type === "start") {
          setStreamSimulated(streamEvent.simulated);
        } else if (streamEvent.type === "saved") {
          setMessages((prev) => [...prev, streamEvent.message]);
          setDraft("");
        } else if (streamEvent.type === "tool") {
          setToolLines((prev) => [...prev, streamEvent.summary]);
        } else if (streamEvent.type === "delta") {
          setStreamText((prev) => prev + streamEvent.text);
        } else if (streamEvent.type === "message") {
          setMessages((prev) => [...prev, streamEvent.message]);
          setStreamingActive(false);
        } else if (streamEvent.type === "error") {
          setToolLines((prev) => [...prev, streamEvent.detail]);
          setStreamingActive(false);
        }
      });
    } finally {
      setBusy(false);
      setStreamingActive(false);
      setStreamText("");
      setToolLines([]);
    }
  }

  function signOut() {
    clearTokens();
    router.replace("/login");
  }

  if (!loaded) {
    return (
      <main className="grid min-h-[60vh] place-items-center text-ink-soft">
        <p>Loading your space…</p>
      </main>
    );
  }

  return (
    <div className="patient-surface mx-auto grid min-h-[calc(100vh-2rem)] max-w-6xl md:grid-cols-[240px_1fr]">
      {/* Left rail */}
      <aside className="border-line px-4 py-6 md:border-r">
        <p className="mb-6 px-2 font-(family-name:--font-display) text-lg font-bold text-ink">
          CareMesh
        </p>
        <nav aria-label="Main" className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) =>
            item === "Chat" ? (
              <span
                key={item}
                className="rounded-control bg-primary-soft px-3 py-2 font-medium text-primary-strong"
              >
                Chat
              </span>
            ) : item === "Resources" ? (
              <Link
                key={item}
                href="/resources"
                className="rounded-control px-3 py-2 text-ink hover:bg-primary-soft/50"
              >
                Resources
              </Link>
            ) : (
              <span
                key={item}
                aria-disabled="true"
                className="flex items-center justify-between px-3 py-2 text-ink-soft/70"
              >
                {item}
                <Chip>soon</Chip>
              </span>
            ),
          )}
        </nav>

        <div className="mt-8">
          <p className="mb-2 px-2 text-[0.8125rem] font-medium text-ink-soft">
            Conversations
          </p>
          <div className="flex flex-col gap-1">
            {conversations.map((c) => (
              <button
                key={c.id}
                onClick={() => selectConversation(c.id)}
                className={`rounded-control px-3 py-2 text-left text-[0.9375rem] ${
                  c.id === selectedId
                    ? "bg-primary-soft text-primary-strong"
                    : "text-ink hover:bg-primary-soft/50"
                }`}
              >
                {c.title}
              </button>
            ))}
          </div>
          <form onSubmit={onStartConversation} className="mt-3 flex flex-col gap-2 px-1">
            <label htmlFor="new-conversation" className="sr-only">
              New conversation topic
            </label>
            <input
              id="new-conversation"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="What is on your mind?"
              className="min-h-11 rounded-control border border-line bg-card px-3 text-[0.9375rem]"
            />
            <Button type="submit" variant="ghost" disabled={!newTitle.trim()}>
              Start conversation
            </Button>
          </form>
        </div>
      </aside>

      {/* Chat column */}
      <main className="flex flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-line px-6 py-4">
          <div>
            <h1 className="font-(family-name:--font-display) text-lg font-bold text-ink">
              Chat
            </h1>
            <p className="text-[0.8125rem] text-ink-soft">
              Dira is an AI companion, not a therapist. Your care team can see
              this space.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <details className="relative">
              <summary className="inline-flex min-h-11 cursor-pointer list-none items-center rounded-control border border-line bg-card px-4 font-medium text-risk">
                Need help now?
              </summary>
              <div className="absolute right-0 z-10 mt-2 w-80 rounded-card border border-line bg-card p-4 text-[0.875rem] shadow-soft">
                <p className="font-medium text-ink">If you need help right now</p>
                <p className="mt-1 text-ink-soft">
                  This app is a portfolio simulation and cannot help in a
                  crisis. Contact your local emergency services, or in the US
                  call or text 988 for the Suicide and Crisis Lifeline.
                </p>
              </div>
            </details>
            <Button variant="ghost" onClick={signOut}>
              Sign out{me ? ` (${me.display_name})` : ""}
            </Button>
          </div>
        </header>

        <div className="mx-auto flex w-full max-w-[720px] flex-1 flex-col gap-3 px-6 py-6">
          {selectedId === null ? (
            <EmptyState
              title="No conversations yet"
              hint="Start one from the left. A short title is enough, like a rough week or exam stress."
            />
          ) : messages.length === 0 ? (
            <EmptyState
              title="This space is yours"
              hint="Write what is going on. There is no wrong way to start."
            />
          ) : (
            messages.map((m) => (
              <ChatBubble
                key={m.id}
                sender={m.sender_type as BubbleSender}
                senderName={m.sender_type === "clinician" ? "Your therapist" : undefined}
                time={timeOf(m.created_at)}
                simulated={m.simulated}
              >
                {m.content}
              </ChatBubble>
            ))
          )}
          {streamingActive ? (
            <div className="flex flex-col gap-1">
              {toolLines.map((line, index) => (
                <p key={index} className="text-[0.8125rem] font-medium text-ai">
                  <span aria-hidden>✦</span> {line}
                </p>
              ))}
              {streamText ? (
                <ChatBubble sender="dira" simulated={streamSimulated}>
                  {streamText}
                </ChatBubble>
              ) : (
                <p className="text-[0.8125rem] text-ink-soft">Dira is thinking…</p>
              )}
            </div>
          ) : null}
          <div ref={endRef} />
        </div>

        {selectedId ? (
          <form
            onSubmit={onSend}
            className="mx-auto flex w-full max-w-[720px] items-end gap-2 px-6 pb-6"
          >
            <label htmlFor="composer" className="sr-only">
              Message
            </label>
            <textarea
              id="composer"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              placeholder="Write a message…"
              className="min-h-11 flex-1 resize-none rounded-control border border-line bg-card px-3.5 py-2.5"
            />
            <Button type="submit" disabled={busy || !draft.trim()}>
              Send
            </Button>
          </form>
        ) : null}
      </main>
    </div>
  );
}
