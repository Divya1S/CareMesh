import type { HTMLAttributes } from "react";

type Tone = "neutral" | "primary" | "ai" | "ok" | "warn" | "risk";

const tones: Record<Tone, string> = {
  neutral: "bg-surface text-ink-soft border-line",
  primary: "bg-primary-soft text-primary-strong border-primary-soft",
  ai: "bg-ai-soft text-ai border-ai",
  ok: "bg-card text-ok border-line",
  warn: "bg-card text-warn border-line",
  risk: "bg-card text-risk border-line",
};

export function Chip({
  tone = "neutral",
  className = "",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-pill border px-2.5 py-0.5 text-[0.75rem] font-medium ${tones[tone]} ${className}`}
      {...props}
    />
  );
}
