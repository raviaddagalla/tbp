"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Bell,
  Camera,
  FileText,
  Factory,
  LayoutDashboard,
  LogOut,
  Map,
  MessageSquareText,
  Search,
  Settings,
  FileBarChart,
  Stethoscope,
  ClipboardCheck,
} from "lucide-react";

import { useAuth, hasRole } from "@/lib/auth";
import { useWs } from "@/lib/ws";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, roles: ["supervisor", "admin"] },
  { href: "/cameras", label: "Live Cameras", icon: Camera, roles: ["worker", "supervisor", "admin"] },
  { href: "/search", label: "Video Search", icon: Search, roles: ["supervisor", "admin"] },
  { href: "/documents", label: "Documents", icon: FileText, roles: ["worker", "supervisor", "admin"] },
  { href: "/chat", label: "Assistant", icon: MessageSquareText, roles: ["worker", "supervisor", "admin"] },
  { href: "/summaries", label: "Shift Summaries", icon: FileBarChart, roles: ["supervisor", "admin"] },
  { href: "/alerts", label: "Safety Alerts", icon: Bell, roles: ["supervisor", "admin"] },
  { href: "/floorplan", label: "Floor Plan", icon: Map, roles: ["supervisor", "admin"] },
  { href: "/diagnostics", label: "Diagnostics", icon: Stethoscope, roles: ["supervisor", "admin"] },
  { href: "/settings", label: "Settings", icon: Settings, roles: ["admin"] },
  { href: "/setup", label: "Setup", icon: ClipboardCheck, roles: ["admin"] },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  if (!user) return null;

  const items = NAV.filter((n) => hasRole(user, n.roles));

  return (
    <aside className="flex h-screen w-16 flex-col border-r border-slate-800 bg-slate-950 lg:w-60">
      <div className="flex items-center gap-3 px-3 py-5 lg:px-5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600">
          <Factory className="h-5 w-5 text-white" />
        </div>
        <div className="hidden lg:block">
          <p className="text-sm font-semibold text-white">Factory Intel</p>
          <p className="text-[11px] text-slate-400">Industry 4.0 Search Platform</p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-2 lg:px-3">
        {items.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-blue-600 text-white"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
              title={item.label}
            >
              <Icon className="h-5 w-5 shrink-0" />
              <span className="hidden lg:inline">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-slate-800 p-3">
        <div className="mb-3 hidden lg:block">
          <p className="truncate text-sm font-medium text-white">{user.full_name || user.username}</p>
          <p className="text-xs capitalize text-slate-400">{user.role}</p>
        </div>
        <button
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 hover:text-white"
        >
          <LogOut className="h-5 w-5 shrink-0" />
          <span className="hidden lg:inline">Sign out</span>
        </button>
      </div>
    </aside>
  );
}

export function ConnectionPill() {
  const { connected } = useWs();
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        connected ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
      }`}
      title="Live event stream"
    >
      <Activity className="h-3 w-3" />
      {connected ? "Live" : "Reconnecting"}
    </span>
  );
}
