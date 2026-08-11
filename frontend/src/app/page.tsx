import Link from "next/link";

/* Lite welcome page. The full marketing landing (DESIGN.md 4.1) is a later
   phase; this page keeps the register and the honesty requirement. */
export default function Home() {
  return (
    <main className="mx-auto flex min-h-[calc(100vh-2rem)] max-w-5xl flex-col px-6">
      <header className="flex items-center justify-between py-6">
        <p className="font-(family-name:--font-display) text-xl font-bold text-ink">
          CareMesh
        </p>
        <Link
          href="/login"
          className="rounded-control px-4 py-2 font-medium text-primary hover:bg-primary-soft"
        >
          Sign in
        </Link>
      </header>

      <section className="grid flex-1 items-center gap-12 py-12 md:grid-cols-2">
        <div>
          <h1 className="font-(family-name:--font-display) text-[2.75rem] leading-[1.15] font-bold text-ink">
            Care that finds its way to you
          </h1>
          <p className="mt-5 max-w-md text-[1.0625rem] text-ink-soft">
            One connected path from a first worry to real support: you, an AI
            companion that knows its limits, and the people who can help.
          </p>
          <div className="mt-8 flex gap-3">
            <Link
              href="/login"
              className="inline-flex min-h-11 items-center rounded-control bg-primary px-6 font-medium text-white transition-colors duration-150 hover:bg-primary-strong"
            >
              Get started
            </Link>
            <Link
              href="/login"
              className="inline-flex min-h-11 items-center rounded-control border border-line bg-card px-6 font-medium text-ink hover:bg-primary-soft"
            >
              For clinicians
            </Link>
          </div>
        </div>

        <svg
          viewBox="0 0 420 300"
          role="img"
          aria-label="A single thread connecting a student, Dira the AI companion, a therapist, and a guardian"
          className="mx-auto w-full max-w-md"
        >
          <path
            d="M40 250 C 120 250 100 150 190 150 S 260 60 330 60 S 390 140 380 200"
            fill="none"
            stroke="var(--primary)"
            strokeWidth="2.5"
            strokeLinecap="round"
          />
          <g fontFamily="var(--font-jakarta)" fontSize="13" fill="var(--ink-soft)">
            <circle cx="40" cy="250" r="10" fill="var(--primary-soft)" stroke="var(--primary)" strokeWidth="2" />
            <text x="40" y="280" textAnchor="middle">Student</text>
            <circle cx="190" cy="150" r="10" fill="var(--ai-soft)" stroke="var(--ai)" strokeWidth="2" />
            <text x="190" y="123" textAnchor="middle" fill="var(--ai)">✦ Dira</text>
            <circle cx="330" cy="60" r="10" fill="var(--primary-soft)" stroke="var(--primary)" strokeWidth="2" />
            <text x="330" y="36" textAnchor="middle">Therapist</text>
            <circle cx="380" cy="200" r="10" fill="var(--primary-soft)" stroke="var(--primary)" strokeWidth="2" />
            <text x="380" y="230" textAnchor="middle">Guardian</text>
          </g>
        </svg>
      </section>

      <footer className="border-t border-line py-6 text-[0.875rem] text-ink-soft">
        CareMesh is a portfolio simulation built to demonstrate engineering, not
        a medical service. Nothing here is real clinical care.
      </footer>
    </main>
  );
}
