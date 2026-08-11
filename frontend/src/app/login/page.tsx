"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { ApiError, login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      router.replace("/chat");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That email and password do not match. Check them and try again."
          : "The server could not be reached. Make sure the backend is running.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="patient-surface mx-auto flex min-h-[80vh] max-w-md flex-col justify-center px-6">
      <h1 className="font-(family-name:--font-display) text-2xl font-bold text-ink">
        Sign in
      </h1>
      <p className="mt-2 mb-6 text-ink-soft">Welcome back to CareMesh.</p>

      <Card className="p-6">
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <Field
            id="email"
            label="Email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Field
            id="password"
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error ? <p className="text-[0.875rem] text-risk">{error}</p> : null}
          <Button type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>

      <Card className="mt-4 p-4 text-[0.875rem] text-ink-soft">
        <p className="mb-1 font-medium text-ink">Demo accounts (seeded data)</p>
        <p className="font-(family-name:--font-mono) text-[0.8125rem]">
          student@demo.caremesh.org
          <br />
          therapist@demo.caremesh.org
        </p>
        <p className="mt-1">
          Password: <span className="font-(family-name:--font-mono)">caremesh-demo</span>
        </p>
      </Card>
    </main>
  );
}
