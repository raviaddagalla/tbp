"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";

import { ConnectionPill, Sidebar } from "@/components/Sidebar";
import { Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return <Spinner label="Loading…" />;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-100">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center justify-end gap-3 border-b border-slate-200 bg-white px-5">
          <ConnectionPill />
          <span className="text-sm text-slate-600">
            {user.full_name || user.username} · <span className="capitalize">{user.role}</span>
          </span>
        </header>
        <main className="flex-1 overflow-y-auto p-5 lg:p-7">{children}</main>
      </div>
    </div>
  );
}
