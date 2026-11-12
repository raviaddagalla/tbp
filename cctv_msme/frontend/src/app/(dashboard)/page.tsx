"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Camera,
  FileText,
  Search,
  Boxes,
  Database,
  Wifi,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PageHeader, Spinner, EmptyState, ErrorState } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth, hasRole } from "@/lib/auth";
import { useWs } from "@/lib/ws";
import { compactNumber, formatDateTime, timeAgo } from "@/lib/format";
import type { ActivityItem, AnalyticsOverview, Camera as CameraModel } from "@/types";

function StatCard({
  icon,
  label,
  value,
  sub,
  accent = "text-blue-600",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <div className={`rounded-lg bg-slate-100 p-2.5 ${accent}`}>{icon}</div>
        <div>
          <p className="text-2xl font-semibold text-slate-900">{value}</p>
          <p className="text-sm text-slate-500">{label}</p>
          {sub && <p className="text-xs text-slate-400">{sub}</p>}
        </div>
      </div>
    </div>
  );
}

const KIND_STYLES: Record<string, string> = {
  camera: "bg-blue-100 text-blue-700",
  document: "bg-violet-100 text-violet-700",
  alert: "bg-red-100 text-red-700",
  search: "bg-emerald-100 text-emerald-700",
  summary: "bg-amber-100 text-amber-700",
  system: "bg-slate-200 text-slate-600",
};

export default function DashboardPage() {
  const { user } = useAuth();
  const canSeeAnalytics = hasRole(user, ["supervisor", "admin"]);
  const { activity: liveActivity, liveAlerts } = useWs();

  const cameras = useQuery({ queryKey: ["cameras"], queryFn: async () => (await api.get<CameraModel[]>("/cameras")).data });
  const analytics = useQuery({
    queryKey: ["analytics"],
    queryFn: async () => (await api.get<AnalyticsOverview>("/analytics/overview")).data,
    enabled: canSeeAnalytics,
  });
  const activityFeed = useQuery({
    queryKey: ["activity"],
    queryFn: async () => (await api.get<ActivityItem[]>("/activity")).data,
  });

  if (cameras.isLoading || (canSeeAnalytics && analytics.isLoading)) {
    return <Spinner label="Loading dashboard…" />;
  }
  const camError = cameras.error || (canSeeAnalytics ? analytics.error : null);
  if (camError) {
    return <ErrorState message="Could not load dashboard data" onRetry={() => cameras.refetch()} />;
  }

  const cams = cameras.data ?? [];
  const online = cams.filter((c) => c.status === "online").length;
  const frames = cams.reduce((s, c) => s + (c.frames_indexed || 0), 0);
  const a = analytics.data;

  const mergedActivity = [
    ...liveActivity.map((x) => ({ id: x.id, kind: x.kind, message: x.message, created_at: x.created_at })),
    ...(activityFeed.data ?? []).map((x) => ({ ...x, id: String(x.id) })),
  ];
  const uniqueActivity = [...new Map(mergedActivity.map((x) => [x.id, x])).values()].slice(0, 12);

  return (
    <div>
      <PageHeader
        title={`Welcome, ${user?.full_name || user?.username}`}
        subtitle="Factory-wide intelligence at a glance"
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-5">
        <StatCard icon={<Wifi className="h-5 w-5" />} label="Cameras online" value={`${online}/${cams.length}`} accent="text-emerald-600" />
        <StatCard icon={<Database className="h-5 w-5" />} label="Frames indexed" value={compactNumber(frames)} />
        <StatCard
          icon={<FileText className="h-5 w-5" />}
          label="Documents"
          value={canSeeAnalytics ? compactNumber(a?.documents_total) : "—"}
          sub={canSeeAnalytics ? `${a?.documents_processed ?? 0} processed` : undefined}
        />
        <StatCard
          icon={<Search className="h-5 w-5" />}
          label="Searches (7d)"
          value={canSeeAnalytics ? compactNumber(a?.searches_last_7d) : "—"}
        />
        <StatCard
          icon={<AlertTriangle className="h-5 w-5" />}
          label="Open alerts"
          value={canSeeAnalytics ? compactNumber(a?.alerts_open) : "—"}
          accent={a?.alerts_open ? "text-red-600" : "text-slate-400"}
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-6">
          {canSeeAnalytics && a && (
            <>
              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h3 className="mb-4 text-sm font-semibold text-slate-800">Searches — last 7 days</h3>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={a.searches_by_day}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="count" name="Searches" fill="#2563eb" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h3 className="mb-3 text-sm font-semibold text-slate-800">Most searched zones</h3>
                {a.top_zones.length === 0 ? (
                  <p className="text-sm text-slate-400">No video searches yet.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {a.top_zones.map((z) => (
                      <span key={z.zone} className="rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-700">
                        {z.zone} · {z.count}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold text-slate-800">Live camera health</h3>
            {cams.length === 0 ? (
              <EmptyState title="No cameras configured" message="Add a camera (RTSP URL or sim://source) from Live Cameras." icon={<Camera className="h-8 w-8" />} />
            ) : (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                {cams.slice(0, 9).map((c) => (
                  <div key={c.id} className="flex items-center gap-3 rounded-lg border border-slate-200 p-3">
                    <span
                      className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                        c.status === "online" ? "bg-emerald-500" : c.status === "reconnecting" ? "bg-amber-500" : "bg-slate-400"
                      }`}
                    />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-800">{c.name}</p>
                      <p className="text-xs text-slate-400">
                        {c.zone} · {compactNumber(c.frames_indexed)} frames
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold text-slate-800">Recent activity</h3>
            {uniqueActivity.length === 0 ? (
              <EmptyState title="No activity yet" message="Camera events, uploads and alerts will appear here." />
            ) : (
              <ul className="space-y-3">
                {uniqueActivity.map((act) => (
                  <li key={act.id} className="flex items-start gap-3">
                    <span className={`mt-0.5 rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase ${KIND_STYLES[act.kind] || KIND_STYLES.system}`}>
                      {act.kind}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm text-slate-700">{act.message}</p>
                      <p className="text-xs text-slate-400">{timeAgo(act.created_at)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {liveAlerts.length > 0 && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-5">
              <h3 className="mb-3 text-sm font-semibold text-red-800">Latest safety alerts</h3>
              <ul className="space-y-2">
                {liveAlerts.slice(0, 4).map((e) => {
                  const p = e.payload as { camera_name: string; zone: string; alert_type: string; timestamp: string };
                  return (
                    <li key={e.type + p.camera_name + p.timestamp} className="text-sm text-red-700">
                      <span className="font-medium capitalize">{p.alert_type.replace("_", " ")}</span> — {p.camera_name}
                      <span className="block text-xs text-red-500">{formatDateTime(p.timestamp)}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      </div>

      {!canSeeAnalytics && (
        <div className="mt-6 flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          <Boxes className="h-4 w-4" /> Your role is limited to your zone ({user?.zone || "—"}). Ask the Assistant for
          procedures or guidance.
        </div>
      )}
    </div>
  );
}
