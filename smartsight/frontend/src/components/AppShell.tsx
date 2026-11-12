"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Camera,
  Eye,
  Film,
  LayoutDashboard,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";

import { api } from "@/lib/api";
import { compactNumber } from "@/lib/format";
import type { AiStatus } from "@/types";

interface HealthResponse {
  status: string;
  app: string;
  camera: string;
  monitoring: boolean;
  ai: AiStatus;
}

const NAV = [
  { href: "/", label: "Overview", short: "Home", icon: LayoutDashboard },
  { href: "/live", label: "Live Camera", short: "Live", icon: Camera },
  { href: "/recordings", label: "Recordings", short: "Clips", icon: Film },
  { href: "/search", label: "Smart Search", short: "Search", icon: Sparkles },
  { href: "/activity", label: "Detection Activity", short: "Activity", icon: Activity },
];

const MOBILE_NAV = [...NAV, { href: "/settings", label: "Settings", short: "Settings", icon: Settings }];

function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => (await api.get<HealthResponse>("/health")).data,
    refetchInterval: 8_000,
    retry: 1,
  });
}

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary via-indigo-500 to-indigo-400 text-white shadow-sm">
        <Eye className="h-5 w-5" />
        <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-white bg-emerald-500" />
      </span>
      {!compact && (
        <span>
          <span className="block text-[15px] font-extrabold leading-none tracking-tight text-ink">
            Smart<span className="text-primary">Sight</span>
          </span>
          <span className="mt-1 block font-mono text-[9px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            AI security camera
          </span>
        </span>
      )}
    </div>
  );
}

function Sidebar({ online, ai }: { online: boolean; ai?: AiStatus }) {
  const pathname = usePathname();
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-white/85 backdrop-blur lg:flex">
      <div className="flex h-16 items-center border-b border-line px-5">
        <Link href="/">
          <BrandMark />
        </Link>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        <p className="px-3 pb-2 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
          Operations
        </p>
        {NAV.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-semibold transition ${
                active
                  ? "bg-primary text-white shadow-sm"
                  : "text-ink-soft hover:bg-surface-container hover:text-ink"
              }`}
            >
              <Icon className={`h-[18px] w-[18px] ${active ? "text-white" : "text-ink-muted group-hover:text-primary"}`} />
              <span className="flex-1">{item.label}</span>
              {item.href === "/live" && online && (
                <span className={`h-1.5 w-1.5 rounded-full ${active ? "bg-white" : "bg-rose-500 live-dot"}`} />
              )}
            </Link>
          );
        })}

        <p className="px-3 pb-2 pt-5 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
          System
        </p>
        <Link
          href="/settings"
          className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-semibold transition ${
            pathname === "/settings" ? "bg-primary text-white" : "text-ink-soft hover:bg-surface-container hover:text-ink"
          }`}
        >
          <Settings className={`h-[18px] w-[18px] ${pathname === "/settings" ? "text-white" : "text-ink-muted group-hover:text-primary"}`} />
          Settings
        </Link>
      </nav>

      <div className="border-t border-line p-3">
        <div className="rounded-2xl bg-surface-low p-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-muted">ESP32-CAM</span>
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                online ? "bg-success-soft text-success" : "bg-danger-soft text-danger"
              }`}
            >
              <span className={`h-1 w-1 rounded-full ${online ? "bg-success" : "bg-danger"}`} />
              {online ? "online" : "offline"}
            </span>
          </div>
          <p className="mt-1.5 truncate font-mono text-[11px] text-ink-soft">YOLOv8n · ByteTrack</p>
          <p className="truncate font-mono text-[11px] text-ink-soft">
            CLIP {ai?.embedder.model || "ViT-B-32"}
          </p>
          <div className="mt-2 flex items-center justify-between border-t border-line pt-2">
            <span className="font-mono text-[10px] text-ink-muted">ChromaDB</span>
            <span className="font-mono text-[10px] font-semibold text-ink-soft">
              {compactNumber(ai?.vector_store.scenes ?? 0)} scenes
            </span>
          </div>
        </div>
        <p className="mt-2 px-1 text-center font-mono text-[9px] uppercase tracking-[0.14em] text-ink-muted">SmartSight v1.0</p>
      </div>
    </aside>
  );
}

function MobileNav() {
  const pathname = usePathname();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
      <div className="no-scrollbar flex items-stretch justify-between px-1">
        {MOBILE_NAV.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-semibold ${
                active ? "text-primary" : "text-ink-muted"
              }`}
            >
              <span className={`rounded-lg px-3 py-1 ${active ? "bg-primary-soft" : ""}`}>
                <Icon className="h-[18px] w-[18px]" />
              </span>
              {item.short}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

function TopBar({ online, cameraStatus }: { online: boolean; cameraStatus: string }) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-line bg-white/80 px-4 backdrop-blur-md sm:px-6">
      <div className="flex items-center gap-2 lg:hidden">
        <BrandMark compact />
        <span className="text-[14px] font-extrabold tracking-tight text-ink">
          Smart<span className="text-primary">Sight</span>
        </span>
      </div>
      <div className="hidden items-center gap-2 lg:flex">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
          Wireless security camera · semantic video search
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${
            online ? "bg-success-soft text-success" : "bg-danger-soft text-danger"
          }`}
          title={`Camera status: ${cameraStatus}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${online ? "bg-success live-dot" : "bg-danger"}`} />
          <span className="hidden sm:inline">{online ? "Live" : "Camera offline"}</span>
          <span className="sm:hidden">{online ? "Live" : "Off"}</span>
        </span>
        <Link
          href="/search"
          className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-3 py-2 text-xs font-semibold text-white transition hover:bg-primary-strong"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Search footage</span>
          <span className="sm:hidden">Search</span>
        </Link>
      </div>
    </header>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const health = useHealth();
  const online = health.data?.camera === "online";
  return (
    <div className="min-h-screen bg-surface">
      <Sidebar online={online} ai={health.data?.ai} />
      <div className="lg:pl-64">
        <TopBar online={online} cameraStatus={health.data?.camera || "unknown"} />
        <main className="mx-auto w-full max-w-[1440px] px-4 pb-28 pt-5 sm:px-6 lg:pb-10 lg:pt-6">{children}</main>
      </div>
      <MobileNav />
    </div>
  );
}
