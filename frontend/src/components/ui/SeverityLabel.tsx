import { AlertTriangle, Info, Minus, OctagonAlert } from "lucide-react";

/**
 * Severity is always icon plus text, never color alone (DESIGN.md 4.4 and
 * the accessibility rule in section 2).
 */
const LEVELS: Record<number, { label: string; tone: string; Icon: typeof Info }> = {
  0: { label: "No concern", tone: "text-ink-soft", Icon: Minus },
  1: { label: "Low", tone: "text-ink-soft", Icon: Info },
  2: { label: "Elevated", tone: "text-warn", Icon: AlertTriangle },
  3: { label: "High", tone: "text-risk", Icon: OctagonAlert },
};

export function SeverityLabel({ severity }: { severity: number }) {
  const level = LEVELS[severity] ?? LEVELS[0];
  const { Icon } = level;
  return (
    <span className={`inline-flex items-center gap-1.5 font-medium ${level.tone}`}>
      <Icon size={16} strokeWidth={1.5} aria-hidden />
      Severity {severity}: {level.label}
    </span>
  );
}
