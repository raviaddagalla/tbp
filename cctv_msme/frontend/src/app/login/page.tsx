"use client";

import React, { useState } from "react";
import { Factory, Loader2 } from "lucide-react";

import { btnPrimary, inputCls } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(errorMessage(err, "Login failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 shadow-lg shadow-blue-900/50">
            <Factory className="h-7 w-7 text-white" />
          </div>
          <div className="text-center">
            <h1 className="text-xl font-semibold text-white">Factory Intelligence Platform</h1>
            <p className="mt-1 text-sm text-slate-400">AI search across your CCTV and factory documents</p>
          </div>
        </div>

        <form onSubmit={submit} className="rounded-2xl bg-white p-6 shadow-2xl">
          <h2 className="mb-4 text-lg font-semibold text-slate-900">Sign in</h2>
          <div className="space-y-4">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Username</span>
              <input
                className={inputCls}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoFocus
                required
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Password</span>
              <input
                className={inputCls}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </label>
            {error && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
            )}
            <button className={`${btnPrimary} w-full justify-center`} disabled={busy}>
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </div>
        </form>

        <div className="mt-6 rounded-xl border border-slate-800 bg-slate-900 p-4 text-xs text-slate-400">
          <p className="mb-2 font-medium text-slate-300">Demo accounts</p>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              ["admin", "admin123", "Admin"],
              ["supervisor", "supervisor123", "Supervisor"],
              ["worker", "worker123", "Worker"],
            ].map(([u, p, label]) => (
              <button
                key={u}
                type="button"
                onClick={() => {
                  setUsername(u);
                  setPassword(p);
                }}
                className="rounded-lg border border-slate-700 px-2 py-1.5 hover:bg-slate-800"
              >
                <span className="block font-medium text-blue-400">{label}</span>
                <span className="block">{u} / {p}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
