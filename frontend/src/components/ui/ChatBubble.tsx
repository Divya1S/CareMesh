import type { ReactNode } from "react";

export type BubbleSender = "patient" | "dira" | "clinician" | "system";

/**
 * Chat bubbles per DESIGN.md 3 and 4.2. Dira is gold (AI), the student is a
 * plain card, clinicians get a rose left border with a name label.
 */
export function ChatBubble({
  sender,
  senderName,
  time,
  children,
}: {
  sender: BubbleSender;
  senderName?: string;
  time?: string;
  children: ReactNode;
}) {
  const mine = sender === "patient";
  const base = "max-w-[85%] rounded-card px-4 py-3 text-[0.9375rem] leading-relaxed";
  const look =
    sender === "dira"
      ? "bg-ai-soft border-l-[1.5px] border-ai"
      : sender === "clinician"
        ? "bg-card border border-line border-l-[3px] border-l-primary"
        : "bg-card border border-line";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div className={`${base} ${look}`}>
        {sender !== "patient" && (
          <p className="mb-1 text-[0.75rem] font-medium text-ink-soft">
            {sender === "dira" ? (
              <span className="text-ai">
                <span aria-hidden>✦</span> Dira · AI companion
              </span>
            ) : (
              (senderName ?? sender)
            )}
          </p>
        )}
        <div className="whitespace-pre-wrap">{children}</div>
        {time ? (
          <p className="mt-1 text-right text-[0.6875rem] text-ink-soft">{time}</p>
        ) : null}
      </div>
    </div>
  );
}
