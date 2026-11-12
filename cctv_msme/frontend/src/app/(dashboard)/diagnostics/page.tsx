"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, Database, Gauge, HardDrive, Server, ShieldCheck } from "lucide-react";

import { ErrorState, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { SystemDiagnostics } from "@/types";

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-1 flex items-center gap-2 text-xs font-medium text-slate-500">
        {icon}
        {label}
      </div>
      <p className="truncate text-lg font-semibold text-slate-900" title={value}>{value}</p>
    </div>
  );
}

export default function DiagnosticsPage() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["diagnostics"],
    queryFn: async () => (await api.get<SystemDiagnostics>("/system/diagnostics")).data,
    refetchInterval: 15000,
  });

  if (isLoading) return <Spinner label="Collecting diagnostics…" />;
  if (error || !data) return <ErrorState message="Could not load diagnostics" onRetry={() => refetch()} />;

  const online = data.cameras.filter((c) => c.status === "online").length;

  return (
    <div>
      <PageHeader
        title="System Diagnostics"
        subtitle={`${data.cameras.length} cameras (${online} online) · backend health, ingest counters and vector-store volumes. Refreshes every 15s.`}
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={<Server className="h-3.5 w-3.5" />} label="Vector store backend" value={data.vector_store_backend} />
        <StatCard icon={<Gauge className="h-3.5 w-3.5" />} label="Queue depth" value={String(data.queue_depth)} />
        <StatCard icon={<Activity className="h-3.5 w-3.5" />} label="Effective sample interval" value={`${data.effective_sample_interval}s`} />
        <StatCard icon={<Cpu className="h-3.5 w-3.5" />} label="Embedding device" value={data.embedding_device} />
        <StatCard icon={<ShieldCheck className="h-3.5 w-3.5" />} label="LLM" value={`${data.llm_provider} / ${data.llm_model}`} />
        <StatCard icon={<ShieldCheck className="h-3.5 w-3.5" />} label="ReID model" value={data.reid_model === "disabled" ? "disabled" : data.reid_model} />
        <StatCard icon={<Database className="h-3.5 w-3.5" />} label="Default retention" value={`${data.retention_hours}h`} />
        <StatCard icon={<HardDrive className="h-3.5 w-3.5" />} label="Data directory" value={data.data_dir} />
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Camera</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Last seen</th>
              <th className="px-4 py-3">Frames indexed</th>
              <th className="px-4 py-3">Alerts</th>
              <th className="px-4 py-3">Inflight</th>
              <th className="px-4 py-3">Object vecs</th>
              <th className="px-4 py-3">Clip-event vecs</th>
              <th className="px-4 py-3">Features</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.cameras.map((c) => (
              <tr key={c.id} className="hover:bg-slate-50">
                <td className="px-4 py-3">
                  <p className="font-medium text-slate-900">{c.name}</p>
                  <p className="text-xs text-slate-400">{c.zone}</p>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={c.status} />
                  {c.last_error && <p className="mt-1 max-w-[220px] truncate text-[10px] text-red-500" title={c.last_error}>{c.last_error}</p>}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {c.last_seen_at ? formatDateTime(c.last_seen_at) : "—"}
                </td>
                <td className="px-4 py-3 tabular-nums text-slate-700">{c.frames_indexed.toLocaleString()}</td>
                <td className="px-4 py-3 tabular-nums text-slate-700">{c.alerts_count}</td>
                <td className="px-4 py-3 tabular-nums text-slate-700">{c.inflight}</td>
                <td className="px-4 py-3 tabular-nums text-slate-700">{c.object_vectors >= 0 ? c.object_vectors.toLocaleString() : "n/a"}</td>
                <td className="px-4 py-3 tabular-nums text-slate-700">{c.clip_event_vectors >= 0 ? c.clip_event_vectors.toLocaleString() : "n/a"}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {c.detector_enabled && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">det</span>}
                    {c.reid_enabled && <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-700">reid</span>}
                    {c.batch_reprocess_enabled && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">reproc</span>}
                    {c.anomaly_enabled && <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700">anomaly</span>}
                  </div>
                </td>
              </tr>
            ))}
            {data.cameras.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-sm text-slate-400">No cameras configured.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
