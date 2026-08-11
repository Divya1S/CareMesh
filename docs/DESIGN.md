# DESIGN.md — CareMesh AI Design Direction

> Authoritative design reference for all frontend work. Read this before building or modifying any UI. If a surface isn't covered here, extend this document first (small ADR-style note at the bottom), then build.
>
> Direction in one line: **the calm confidence of a modern wellness brand (Wix health-template energy) on the marketing and patient-facing surfaces, tightening into a precise clinical/engineering workbench on the professional surfaces — one token system underneath both.**

---

## 1. Design thesis

CareMesh is a care *network* for young people. The design should feel like being held by a system that is organized on your behalf: soft, unhurried, and human on the outside; legible, dense, and trustworthy on the inside. It must never feel like a hospital form, and never like a generic SaaS admin panel.

**Signature element — the Care Thread.** A single continuous, softly curved line that connects nodes (people, events, steps). It appears as:
- the hero illustration on the landing page (thread linking student → Dira → clinician → guardian nodes),
- the connector in the patient timeline,
- the progress indicator in multi-step flows (referrals, consent, claims),
- a subtle footer motif.

This is the one memorable device. Everything else stays quiet and disciplined. Do not add additional decorative illustration systems, mascots, or gradient blobs.

**One structural color rule that carries meaning:** deep gold always and only means "AI." No other element uses the AI gold; AI content never appears without it. Paired with the ✦ sparkle mark, this makes the build spec's AI-provenance requirement *visible* rather than a label bolted on.

**Hard palette constraint (owner's requirement):** no blue, dark blue, navy, indigo, or violet — or any hue adjacent to them — anywhere in the product. The palette is led by muted, professional rose/pink, supported by warm neutrals, gold, orange, and green for semantics. Grays must be warm/rose-tinted, never blue-tinted. Pink must never drift toward magenta-violet (see hue guard in §2). This applies to charts, gradients, illustrations, focus rings, and third-party component defaults (audit shadcn/chart library defaults, which often ship blue).

---

## 2. Tokens

Define these as CSS variables + Tailwind theme extensions in one place (`frontend/src/styles/tokens.css`). No hardcoded hex values in components.

### Color

| Token | Hex | Use |
|---|---|---|
| `--ink` | `#332327` | Primary text — deep mulberry-charcoal (warm, never blue-black) |
| `--ink-soft` | `#6E585E` | Secondary text, captions |
| `--surface` | `#FBF7F7` | App/page background (off-white with a faint blush tint) |
| `--card` | `#FFFFFF` | Cards, panels |
| `--line` | `#F0E3E5` | Borders, dividers, hairlines (rose-tinted gray) |
| `--primary` | `#A63E56` | Deep dusty rose — buttons, links, active states, the Care Thread |
| `--primary-strong` | `#872F45` | Hover/pressed |
| `--primary-soft` | `#F7E6EA` | Selected fills, soft badges, thread node halos |
| `--ai` | `#9C6B1E` | **AI-provenance gold** (deep ochre). AI chips, AI card borders, Dira accents. Reserved — nothing else may use this hue. |
| `--ai-soft` | `#F6EDDA` | AI card backgrounds, Dira message bubbles (soft gold tint) |
| `--warn` | `#BE5B2A` | Moderate risk, pending states (burnt orange) |
| `--risk` | `#8F2D24` | High risk, errors (deep brick — darker and browner than the rose, always paired with icon + label) |
| `--ok` | `#3E7C4F` | Success, resolved (forest green) |

**Hue guard for the pink:** keep `--primary` and every rose tint in the 345–355° hue range (red-pink side). Anything below ~335° starts reading magenta → violet and violates the hard constraint; pull it back toward red. The professionalism of this palette lives in *saturation discipline*: the deep rose is the only saturated pink; everything else is a barely-there tint. Rose ≠ risk: `--risk` brick is markedly darker/browner than `--primary`, and severity always carries icon + text, never color alone.

**How pink stays professional (binding usage rules):**
- Pink is an *accent system*, not wallpaper: large areas are `--surface`/`--card`; deep rose appears in controls, links, the Thread, key headings — roughly ≤10% of any screen's area.
- No bubblegum, neon, or hot pink anywhere; no pink-on-pink text; no pink gradients.
- Rose + gold + mulberry ink is the brand chord — an editorial, almost print-like combination. Let generous whitespace and the Sora/Jakarta type pairing do the "premium" work; the color just signs it.
- Clinician and ops surfaces bias even further neutral: rose only in interactive elements and the Thread, so dense screens stay calm.

Risk severity is never communicated by color alone — always icon + text label alongside (accessibility + a mental-health product should not scream red at anyone).

Optional **graphite variant** for the Ops Console only (`--surface: #1B211F`, `--card: #232B28`, ink inverted): gives the internal control plane an engineering-room feel. Implement only if cheap once tokens exist; otherwise ops stays light.

### Type

- **Display: Sora** — geometric, friendly, modern. Headings, hero, numbers. Weights 600/700 only. Use with restraint: display face on headings, never on body.
- **Body: Plus Jakarta Sans** — warm, rounded, highly readable. 400/500/600.
- **Utility: JetBrains Mono** — IDs, event names, token counts, code, ops tables.

Scale (rem): `display 3.5 / h1 2.25 / h2 1.5 / h3 1.25 / body 1 / small 0.875 / micro 0.75`. Line-height 1.6 body, 1.15 display. Patient-facing surfaces use body at 1.0625rem (17px) — slightly larger, calmer. Clinician/ops surfaces may drop to 0.9375rem for density.

### Space, shape, elevation, motion

- **Spacing:** 4px base grid; sections on marketing pages breathe at 96–128px vertical; app surfaces use 16/24 rhythm.
- **Radius:** `--r-card: 16px`, `--r-control: 10px`, `--r-pill: 999px`. Rounded but not bubbly. Ops tables: 8px.
- **Shadow:** one soft ambient shadow only (`0 1px 2px rgb(23 48 43 / .05), 0 8px 24px rgb(23 48 43 / .06)`). No stacked/glow shadows.
- **Motion:** 150–200ms ease-out for hovers/toggles; 300ms for panel/sheet entrances; one orchestrated moment per page maximum (e.g., landing hero: thread draws itself once on load via SVG stroke animation). Respect `prefers-reduced-motion` — thread renders static. Dira's typing indicator: three soft dots, no orb pulsing, no gimmicks.

---

## 3. AI provenance UI (build-spec requirement, made concrete)

Every AI-generated element, everywhere, renders inside an **AI frame**:
- `--ai-soft` background or a 1.5px `--ai` left border,
- a pill chip: `✦ AI-generated` (gold), with model + prompt version on hover/tap,
- when applicable, a provenance row: sources cited (RAG), confidence/score, timestamp.

Clinician review controls (**Accept / Edit / Reject**) sit directly on the AI frame, not in a distant toolbar. On Accept, the frame visually transitions: gold border → rose, chip changes to `Approved by Dr. ___` with timestamp. The state change *is* the UI — this is the "AI suggestion never silently becomes a clinician decision" rule, rendered.

Dira's chat: Dira bubbles are `--ai-soft` with the ✦ mark in the avatar; student bubbles are `--card` with `--line` border. Dira's disclosure line ("I'm an AI companion, not a therapist") is persistent in the chat header, not a dismissible toast.

---

## 4. Surface-by-surface layout specs

### 4.1 Public landing page (the most Wix-like artifact)
Marketing layout, generous whitespace, sticky translucent header.
1. **Hero:** left — display headline ("Care that finds its way to you" register: warm, specific, no jargon), subline, two CTAs (`Get started` deep rose, `For clinicians` ghost); right — animated Care Thread illustration linking four labeled nodes (Student · Dira · Therapist · Guardian).
2. **How it works:** 3 steps connected by the thread (this is a real sequence, so numbering is earned).
3. **Surfaces strip:** role cards (Student / Guardian / Clinician / School) each with one sentence and a "Sign in as…" link — doubles as the demo entry point.
4. **Trust section:** plain-language safety commitments + the mandatory disclosure: *"CareMesh is a portfolio simulation, not a medical service."* Styled honestly, visible, not fine print.
5. Footer with thread motif.

### 4.2 Student app + Dira
Chat-first, single-column, max-width 720px, larger body type, `--surface` background. Left rail (collapsible on mobile): Home, Chat with Dira, Appointments, My care team, Resources. Structured Dira actions (schedule, assessment) render as inline cards inside the conversation — chat is the spine, not a widget farm. Crisis-resources entry point is always visible in the header — one tap, never buried.

### 4.3 Guardian portal
Calm card grid, no data tables. Cards: care status (only what's authorized — the card itself says "Shared with you by the care team"), upcoming appointments, notifications, consent requests (thread-stepper flow), resources. Empty states are invitations ("No appointments yet — request one"), never blank panels.

### 4.4 Clinician workspace (the workbench)
Three-pane: **left** patient list with risk-sorted queue (240px); **center** patient timeline — events as nodes on the vertical Care Thread (messages, risk signals, appointments, notes; AI items in AI frames); **right** context panel (care plan, tasks, alerts, AI summary with Accept/Edit/Reject). Denser type scale, keyboard-first (j/k through queue, enter to open, a/e/r on focused AI items). Risk queue rows: severity icon + label + time-since-signal; never color-only.

### 4.5 School dashboard
Roster table + referral flow. Referral submission is a thread-stepper (Student → Concern → Consent check → Submitted). Status chips mirror workflow states exactly (same names as the backend state machine — vocabulary consistency). Aggregate trends as simple bar/line cards; no vanity charts.

### 4.6 Payer dashboard
This is state-machine UI: claims table (mono for IDs/amounts) with an expandable state-history rail per claim — each transition timestamped, actor-attributed, using the thread connector vertically. Denial tracking is a filtered view, not a separate page.

### 4.7 Ops console
Engineering room. Dense tables (mono), workflow inspector showing the state machine as nodes-on-thread with the failed node in `--risk`, DLQ browser, AI request inspector (prompt/response/tokens/cost/trace), retry/replay buttons with confirm-dialogs that state idempotency implications in plain language. Optional graphite theme. This surface is allowed to look powerful rather than soft — same tokens, tighter spacing, zero marketing air.

---

## 5. Component inventory (build once in Phase 2, reuse everywhere)

Base on shadcn/ui primitives restyled to these tokens: Button (primary/ghost/destructive), Card, AIFrame (the provenance wrapper — build this early, everything depends on it), Chip/Badge, ThreadStepper, ThreadTimeline, DataTable (sortable, paginated, mono option), ChatBubble (user/dira), EmptyState, StatCard, StatusChip (workflow-state-driven), ConfirmDialog, Toast, Sheet/Drawer, Field components with visible error text. No component ships without: loading, empty, error, and keyboard-focus states.

---

## 6. Copy voice

Plain verbs, sentence case, second person, no filler. Buttons say what happens: "Request appointment," not "Submit." An action keeps its name through the flow (button "Publish note" → toast "Note published"). Errors state what happened and what to do next; they don't apologize and are never vague. Patient-facing copy is warm and concrete; clinician/ops copy is terse and exact. Never use clinical-authority language for AI output ("Dira noticed…" / "Suggested summary," never "Diagnosis" or "Assessment result").

---

## 7. Quality floor (non-negotiable, unannounced)

Responsive to 360px; WCAG AA contrast (all token pairs above pass — verify when changing); visible keyboard focus (`--primary` 2px offset ring); reduced-motion respected; touch targets ≥ 44px on patient/guardian surfaces; no layout shift on load (skeletons match final geometry).

---

## 8. Anti-generic calibration (what NOT to ship)

- **No blue, navy, indigo, or violet in any shade, anywhere** — hard product constraint (see §2). Audit every chart palette, gradient, illustration, and library default; focus rings and links use `--primary` rose, never browser-default blue.
- **No unprofessional pink:** no bubblegum/neon/hot pink, no pink gradients, no pink page backgrounds beyond the faint `--surface` blush, no rose exceeding ~10% of a screen's area. If a screen reads "beauty brand" instead of "healthcare platform," desaturate and cut.
- No cream + terracotta + serif "AI default" look; no black + acid-green; no zero-radius broadsheet.
- No purple-to-blue gradient heroes, no glassmorphism, no floating 3D blobs, no emoji as icons (use Lucide, 1.5px stroke).
- No numbered section markers unless the content is genuinely sequential.
- No dashboard stat-card rows as a hero.
- If a screen would look at home in any generic admin template, it's wrong — find what's specific to *this* screen's job and let that drive the layout.

## 9. Working method for UI phases

1. Before building a surface, restate its single job and sketch the layout against §4.
2. Build with tokens only; extend tokens rather than inlining values.
3. Screenshot the rendered result and self-critique against §8 before presenting.
4. When the human provides Wix template screenshots as references, extract *structure and mood* (spacing, hierarchy, section rhythm) — never copy imagery, illustration, or copy text.

---

*Change log: extend below with dated notes when this direction evolves.*

- 2026-08-10 (S7): Ops console shipped light (same tokens, denser rhythm, mono for ids, zero marketing air per §4.7). The optional graphite variant was skipped for now per the "only if cheap" rule; revisit when the ops surface grows in the full ops phase. Confirm dialog copy for event republish states the idempotency implication in plain language, per §4.7.
- 2026-08-10 (S2): Token system implemented in `frontend/src/styles/tokens.css` exactly per §2 (fonts via next/font: Sora, Plus Jakarta Sans, JetBrains Mono). First components shipped hand-rolled on the tokens (Button, Card, Chip, AIFrame, ChatBubble, EmptyState, Field) rather than on shadcn/ui: S2 needed no overlay primitives, and adopting Radix-based shadcn is deferred to the first phase that needs Dialog/Sheet/Toast/DataTable (per §5 the API surface stays the same). Welcome page ships as a lite version of §4.1 (hero register, thread illustration, trust disclosure); the full marketing landing with animation comes with a later polish phase. Chat rail navigation shows future surfaces as visibly disabled "soon" items rather than hiding them.
