import type { ReactNode } from "react";

/** Empty states are invitations, never blank panels (DESIGN.md 4.3). */
export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-card border border-dashed border-line bg-card px-6 py-12 text-center">
      <p className="font-medium text-ink">{title}</p>
      {hint ? <p className="max-w-sm text-[0.875rem] text-ink-soft">{hint}</p> : null}
      {action}
    </div>
  );
}
