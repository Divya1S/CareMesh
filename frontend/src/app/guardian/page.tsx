"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { getMe, guardianOverview, type GuardianOverview, type Me } from "@/lib/api";
import { clearTokens, isLoggedIn } from "@/lib/auth";

/* Calm card grid, no data tables (DESIGN.md 4.3). Everything here was
   explicitly shared by the care team; empty states are invitations. */

export default function GuardianPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [overview, setOverview] = useState<GuardianOverview | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const profile = await getMe();
        if (profile.role !== "guardian") {
          router.replace("/login");
          return;
        }
        setMe(profile);
        setOverview(await guardianOverview());
      } catch {
        clearTokens();
        router.replace("/login");
      } finally {
        setLoaded(true);
      }
    })();
  }, [router]);

  function signOut() {
    clearTokens();
    router.replace("/login");
  }

  if (!loaded || !overview) {
    return (
      <main className="grid min-h-[60vh] place-items-center text-ink-soft">
        <p>Loading your portal…</p>
      </main>
    );
  }

  return (
    <main className="patient-surface mx-auto max-w-4xl px-6 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-(family-name:--font-display) text-xl font-bold text-ink">
            Guardian portal
          </h1>
          <p className="text-[0.8125rem] text-ink-soft">
            You see what the care team shares with you. Conversations and care
            records stay private between your student and their care team.
          </p>
        </div>
        <Button variant="ghost" onClick={signOut}>
          Sign out{me ? ` (${me.display_name})` : ""}
        </Button>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-2 font-semibold text-ink">Your student</h2>
          {overview.students.length === 0 ? (
            <p className="text-ink-soft">
              No student is linked to you yet. The care team sets this up.
            </p>
          ) : (
            overview.students.map((s) => (
              <p key={s.patient_id as string} className="text-ink">
                {s.name as string}{" "}
                <span className="text-[0.8125rem] text-ink-soft">
                  · linked by the care team
                </span>
              </p>
            ))
          )}
        </Card>

        <Card className="p-5">
          <h2 className="mb-2 font-semibold text-ink">Notifications</h2>
          {overview.notifications.length === 0 ? (
            <p className="text-ink-soft">
              Nothing right now. You will hear from us when something needs you.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {overview.notifications.map((n) => (
                <li key={n.id as string} className="text-[0.9375rem] text-ink">
                  <Chip tone="primary">{(n.kind as string).replace("_", " ")}</Chip>{" "}
                  {n.content as string}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="p-5">
          <h2 className="mb-2 font-semibold text-ink">Care updates</h2>
          <p className="mb-2 text-[0.75rem] text-ink-soft">
            Shared with you by the care team.
          </p>
          {overview.updates.length === 0 ? (
            <p className="text-ink-soft">
              No updates yet. The care team writes these when there is
              something worth sharing.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {overview.updates.map((u) => (
                <li key={u.id as string}>
                  <p className="text-ink">{u.content as string}</p>
                  <p className="text-[0.75rem] text-ink-soft">
                    {u.author_name as string} about {u.patient_name as string}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="p-5">
          <h2 className="mb-2 font-semibold text-ink">Resources</h2>
          <p className="mb-3 text-ink-soft">
            The same resource library your student can use.
          </p>
          <Link
            href="/resources"
            className="inline-flex min-h-11 items-center rounded-control border border-line bg-card px-4 font-medium text-primary hover:bg-primary-soft"
          >
            Open resources
          </Link>
        </Card>
      </div>
    </main>
  );
}
