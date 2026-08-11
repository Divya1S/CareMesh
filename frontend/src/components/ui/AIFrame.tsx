import type { ReactNode } from "react";
import { Chip } from "./Chip";

/**
 * The AI provenance wrapper from DESIGN.md section 3. Every AI generated
 * element in the product renders inside this frame. Gold is reserved for AI.
 */
export function AIFrame({
  children,
  model,
  promptVersion,
  simulated,
  className = "",
}: {
  children: ReactNode;
  model?: string;
  promptVersion?: string;
  simulated?: boolean;
  className?: string;
}) {
  const provenance = [model, promptVersion].filter(Boolean).join(" · ");
  return (
    <div
      className={`rounded-card border-l-[1.5px] border-ai bg-ai-soft p-4 ${className}`}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Chip tone="ai" title={provenance || undefined}>
          <span aria-hidden>✦</span> AI generated
        </Chip>
        {simulated ? (
          <Chip tone="ai" title="Produced by the fake provider, not a real model">
            SIMULATED
          </Chip>
        ) : null}
      </div>
      {children}
    </div>
  );
}
