"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Download, FileText, History, Loader2, MapPin, Play, XCircle } from "lucide-react";

import { EmptyState, ErrorState, Modal, PageHeader, Spinner, StatusBadge, btnPrimary, btnSecondary, inputCls } from "@/components/ui";
import { PlaybackModal } from "@/components/VideoPlayer";
import { api, errorMessage } from "@/lib/api";
import { useAuth, hasRole } from "@/lib/auth";
import { useWs } from "@/lib/ws";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { Alert, AlertTimeline } from "@/types";

export default function AlertsPage() {
  const { user } = useAuth();
  const isSupervisor = hasRole(user, ["supervisor", "admin"]);
  const { liveAlerts } = useWs();
  const [type, setType] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<{ alert: Alert; data: AlertTimeline | null } | null>(null);
  const [playing, setPlaying] = useState<{ src: string; title: string; offset: number } | null>(null);

  const { data: alerts, isLoading, error: loadError, refetch } = useQuery({
    queryKey: ["alerts"],
    queryFn: async () => (await api.get<Alert[]>("/alerts")).data,
  });

  const liveKeys = useMemo(() => new Set(liveAlerts.map((a) => `${a.payload.camera_id}_${a.payload.timestamp}`)), [liveAlerts]);

  const filtered = useMemo(
    () =>
      (alerts ?? []).filter(
        (a) => (!type || a.alert_type === type) && (!status || a.status === status)
      ),
    [alerts, type, status]
  );

  const acknowledge = async (a: Alert) => {
    await api.post(`/alerts/${a.id}/acknowledge`);
    await refetch();
  };

  const dismiss = async (a: Alert) => {
    await api.post(`/alerts/${a.id}/dismiss`);
    await refetch();
  };

  const generateReport = async (a: Alert) => {
    setBusyId(a.id);
    setError(null);
    try {
      await api.post(`/alerts/${a.id}/report`, { generate_report: true });
      await refetch();
    } catch (err) {
      setError(errorMessage(err, "Could not generate report"));
    } finally {
      setBusyId(null);
    }
  };

  const exportReport = async (a: Alert) => {
    const res = await api.post(`/alerts/${a.id}/export?format=txt`, undefined, { responseType: "blob" });
    const url = URL.createObjectURL(res.data as Blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `incident_${a.id}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const openTimeline = async (a: Alert) => {
    setTimeline({ alert: a, data: null });
    try {
      const res = await api.get<AlertTimeline>(`/alerts/${a.id}/timeline`);
      setTimeline({ alert: a, data: res.data });
    } catch (err) {
      setTimeline({ alert: a, data: null });
      setError(errorMessage(err, "Could not load timeline"));
    }
  };

  if (isLoading) return <Spinner label="Loading alerts…" />;
  if (loadError) return <ErrorState message="Could not load alerts" onRetry={() => refetch()} />;

  return (
    <div>
      <PageHeader
        title="Safety Alerts"
        subtitle="Zero-shot anomaly detection — no helmet, smoke/fire, restricted zone, spill — with cross-camera movement trails"
      />

      {error && <div className="mb-4"><p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p></div>}

      {liveAlerts.length > 0 && (
        <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4">
          <p className="mb-2 text-sm font-semibold text-red-800">
            <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-red-500" />
            Live alerts now
          </p>
          <div className="flex flex-wrap gap-2">
            {liveAlerts.map((e, i) => {
              const p = e.payload as { camera_name: string; alert_type: string; timestamp: string };
              return (
                <span key={i} className="rounded-full bg-white px-3 py-1 text-xs text-red-700">
                  {p.camera_name} — {p.alert_type.replace("_", " ")} · {timeAgo(p.timestamp)}
                </span>
              );
            })}
          </div>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <select className={inputCls + " w-auto"} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All alert types</option>
          <option value="no_helmet">No helmet</option>
          <option value="smoke_fire">Smoke / fire</option>
          <option value="restricted_zone">Restricted zone</option>
          <option value="spill">Spill</option>
        </select>
        <select className={inputCls + " w-auto"} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All states</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="dismissed">Dismissed</option>
        </select>
        {isSupervisor && <p className="ml-auto text-xs text-slate-400">{filtered.length} alerts</p>}
      </div>

      {filtered.length === 0 ? (
        <EmptyState title="No alerts" message="Anomaly detection is per-camera opt-in. Enable it when adding or editing a camera." />
      ) : (
        <div className="space-y-3">
          {filtered.map((a) => {
            const live = liveKeys.has(`${a.camera_id}_${a.timestamp}`);
            return (
              <div key={a.id} className={`rounded-xl border bg-white p-4 shadow-sm ${live ? "border-red-300 ring-1 ring-red-100" : "border-slate-200"}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase ${a.alert_type === "smoke_fire" ? "bg-red-100 text-red-700" : a.alert_type === "no_helmet" ? "bg-amber-100 text-amber-700" : "bg-orange-100 text-orange-700"}`}>
                        {a.alert_type.replace(/_/g, " ")}
                      </span>
                      <span className="text-sm font-semibold text-slate-900">{a.camera_name}</span>
                      <span className="text-xs text-slate-400">{timeAgo(a.timestamp)}</span>
                    </div>
                    <p className="mt-1 text-sm text-slate-600">{a.description}</p>
                    <p className="mt-0.5 text-xs text-slate-400">Confidence {Math.round(a.score * 100)}% · {formatDateTime(a.timestamp)}</p>
                    {a.trail.length > 1 && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                        <MapPin className="h-3 w-3 text-blue-500" />
                        {a.trail.map((t, i) => (
                          <span key={i} className="flex items-center gap-1">
                            {i > 0 && <span className="text-slate-300">→</span>}
                            <span className="rounded bg-blue-50 px-1.5 py-0.5" title={`Stitch confidence ${Math.round(t.score * 100)}%`}>
                              {t.camera_name} · {timeAgo(t.timestamp)}
                              <span className={`ml-1 font-semibold ${t.score >= 0.4 ? "text-emerald-600" : t.score >= 0.2 ? "text-amber-600" : "text-slate-400"}`}>
                                {Math.round(t.score * 100)}%
                              </span>
                            </span>
                          </span>
                        ))}
                      </div>
                    )}
                    {a.report && (
                      <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
                        <span className="font-semibold uppercase tracking-wide text-slate-400">Incident report — </span>
                        {a.report}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusBadge status={a.status === "acknowledged" ? "acknowledged" : a.status === "dismissed" ? "dismissed" : "active"} />
                    {isSupervisor && (
                      <>
                        <button className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" onClick={() => openTimeline(a)} title="Timeline">
                          <History className="h-3.5 w-3.5" />
                        </button>
                        <button className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" onClick={() => generateReport(a)} disabled={busyId === a.id} title="Generate incident report">
                          {busyId === a.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />}
                        </button>
                        <button className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" onClick={() => exportReport(a)} title="Export report">
                          <Download className="h-3.5 w-3.5" />
                        </button>
                        {a.status !== "acknowledged" && a.status !== "dismissed" && (
                          <>
                            <button className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" onClick={() => acknowledge(a)}>
                              <CheckCircle2 className="mr-1 inline h-3 w-3" /> Acknowledge
                            </button>
                            <button className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50" onClick={() => dismiss(a)} title="Mark as resolved / false positive">
                              <XCircle className="mr-1 inline h-3 w-3" /> Dismiss
                            </button>
                          </>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Modal open={timeline !== null} onClose={() => setTimeline(null)} title={`Timeline — ${timeline?.alert.camera_name ?? ""}`}>
        {timeline && !timeline.data && <Spinner label="Loading timeline clips…" />}
        {timeline && timeline.data && (
          <div className="space-y-2">
            <p className="text-xs text-slate-500">
              Clips within ±3 minutes of the alert at <span className="font-medium">{formatDateTime(timeline.alert.timestamp)}</span> (UTC).
            </p>
            {timeline.data.clips.length === 0 ? (
              <p className="text-sm text-slate-400">No rolling clips retained for this window.</p>
            ) : (
              timeline.data.clips.map((c) => (
                <button
                  key={c.segment_id}
                  className="flex w-full items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-left hover:bg-slate-50"
                  onClick={() =>
                    setPlaying({
                      src: c.clip_url,
                      title: `${timeline.alert.camera_name} — ${formatDateTime(new Date(c.start * 1000).toISOString())}`,
                      offset: 0,
                    })
                  }
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white">
                    <Play className="h-3.5 w-3.5" />
                  </span>
                  <span className="truncate text-sm text-slate-700">{formatDateTime(new Date(c.start * 1000).toISOString())}</span>
                  {c.segment_id === (timeline.alert.clip_url?.split("/").pop() ?? "").replace(".mp4", "") && (
                    <span className="ml-auto rounded bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700">ALERT SEGMENT</span>
                  )}
                </button>
              ))
            )}
            <div className="flex justify-end pt-2">
              <button className={btnSecondary} onClick={() => setTimeline(null)}>Close</button>
            </div>
          </div>
        )}
      </Modal>

      {playing && (
        <PlaybackModal
          src={playing.src}
          offsetSeconds={playing.offset}
          title={playing.title}
          onClose={() => setPlaying(null)}
        />
      )}
    </div>
  );
}
