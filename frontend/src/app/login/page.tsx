"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ApiError, apiPost } from "@/lib/api/client";

export default function LoginPage() {
  const router = useRouter();
  const client = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/v1/auth/login", { email, password });
      await client.invalidateQueries();
      router.replace("/");
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "The server could not be reached.");
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-4 rounded border border-line bg-panel p-6"
      >
        <h1 className="text-lg font-semibold">AI Trading Intelligence</h1>
        <div>
          <label htmlFor="email" className="mb-1 block text-sm text-muted">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="min-h-11 w-full rounded border border-line bg-surface px-3 text-base"
          />
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-sm text-muted">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby={error ? "login-error" : undefined}
            className="min-h-11 w-full rounded border border-line bg-surface px-3 text-base"
          />
          {error ? (
            <p id="login-error" role="alert" className="mt-2 text-sm text-bad">
              {error}
            </p>
          ) : null}
        </div>
        <button
          type="submit"
          disabled={busy}
          className="min-h-11 w-full cursor-pointer rounded bg-ink font-semibold text-surface transition-opacity duration-150 disabled:cursor-wait disabled:opacity-60"
        >
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>
    </main>
  );
}
