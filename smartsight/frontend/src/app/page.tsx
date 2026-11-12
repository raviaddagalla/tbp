"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  Camera as CameraIcon,
  CirclePlay,
  Clock3,
  Database,
  Film,
  Layers,
  MonitorPlay,
  Play,
  ScanEye,
  Sparkles,
  Square,
  Wifi,
} from "lucide-react";

import { AppShell } from "@/components/AppShell";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  ScoreBar,
  Skeleton,
  StatCard,
  StatusPill,
  btnPrimary,
  btnSecondary,
} from "@/components/ui";
import { api, apiUrl, errorMessage } from "@/lib/api";
import { compactNumber, formatClock, formatDateTime, timeAgo, titleCase } from "@/lib/format";
import type { LiveDetectionsResponse, OverviewResponse } from "@/types";

const KIND_TONE: Record<string, "primary" | "success" | "warn" | "danger" | "neutral"> = {
  camera: "primary",
  recording: "success",
  system: "neutral",
  search: "primary",
};

export default function OverviewPage() {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState("");

  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: async () => (await api.get<OverviewResponse>("/overview")).data,
    refetchInterval: 5_000,
  });
  const live = useQuery({
    queryKey: ["camera-detections"],
    queryFn: async () => (await api.get<LiveDetectionsResponse>("/camera/detections")).data,
    refetchInterval: 2_000,
  });

  const control = useMutation({
    mutationFn: async (action: "start" | "stop") => (await api.post(`/camera/${action}`)).data,
    onSuccess: () => {
      setActionError("");
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["camera-detections"] });
      queryClient.invalidateQueries({ queryKey: ["camera-status"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
    onError: (err) => setActionError(errorMessage(err, "Could not change monitoring state")),
  });

  if (overview.isLoading) {
    return (
      <AppShell>
        <PageHeader title="Overview" subtitle="Your camera, detections and search index at a glance." />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[0, 1, 2, 3].map((key) => (
            <Skeleton key={key} className="h-24" />
          ))}
        </div>
        <Skeleton className="mt-4 h-80" />
      </AppShell>
    );
  }

  if (overview.isError || !overview.data) {
    return (
      <AppShell>
        <PageHeader title="Overview" />
        <ErrorState message={errorMessage(overview.error, "Could not load the dashboard")} onRetry={() => overview.refetch()} />
      </AppShell>
    );
  }

  const data = overview.data;
  const camera = data.camera;
  const online = camera.status === "online";
  const simulated = camera.source_kind === "simulated";
  const activeTracks = live.data?.detections ?? [];
  const totals = data.totals;
  const ai = data.ai;
  const storage = data.storage;

  const storageTotal =
    storage.database.bytes + storage.thumbnails.bytes + storage.snapshots.bytes + storage.recordings.bytes + storage.vectorstore.bytes;
  const storageRows = [
    { label: "Recordings", bytes: storage.recordings.bytes, colour: "bg-primary" },
    { label: "Vector store", bytes: storage.vectorstore.bytes, colour: "bg-indigo-400" },
    { label: "Thumbnails", bytes: storage.thumbnails.bytes, colour: "bg-emerald-400" },
    { label: "Database", bytes: storage.database.bytes, colour: "bg-amber-400" },
  ];
  const percent = (part: number) => (storageTotal > 0 ? Math.max(2, Math.round((part / storageTotal) * 100)) : 0);
  const topClass = totals.object_classes[0];

  return (
    <AppShell>
      <PageHeader
        eyebrow="Command center"
        title="Overview"
        subtitle="Live ESP32-CAM status, detection activity and the semantic index behind Smart Search."
        actions={
          <>
            <button onClick={() => overview.refetch()} className={btnSecondary}>
              Refresh
            </button>
            <Link href="/live" className={btnPrimary}>
              <MonitorPlay className="h-4 w-4" /> Open live camera
            </Link>
          </>
        }
      />

      {/* Camera status strip */}
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
          <div className="flex items-start gap-3">
            <span
              className={`mt-0.5 flex h-11 w-11 items-center justify-center rounded-2xl ${
                online ? "bg-success-soft text-success" : "bg-surface-container text-ink-muted"
              }`}
            >
              <CameraIcon className="h-5 w-5" />
            </span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold text-ink">ESP32-CAM</h2>
                <StatusPill status={camera.status} />
                {simulated && <Badge tone="warn">simulated source</Badge>}
                {camera.detector_enabled ? <Badge tone="primary">detection on</Badge> : <Badge>detection off</Badge>}
              </div>
              <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">{camera.source_url || "No source configured"}</p>
              <p className="mt-1 text-xs text-ink-soft">
                {camera.source_label || "No frames yet"}
                {online && camera.frame_width > 0 ? ` · ${camera.frame_width}×${camera.frame_height}` : ""}
                {online ? ` · ${camera.measured_fps.toFixed(1)} fps processed` : ""}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {camera.running ? (
              <button onClick={() => control.mutate("stop")} disabled={control.isPending} className={btnSecondary}>
                <Square className="h-3.5 w-3.5" /> Stop monitoring
              </button>
            ) : (
              <button onClick={() => control.mutate("start")} disabled={control.isPending} className={btnPrimary}>
                <Play className="h-3.5 w-3.5" /> Start monitoring
              </button>
            )}
            <Link href="/settings" className={btnSecondary}>
              Settings
            </Link>
          </div>
        </div>
        {(actionError || camera.last_error) && (
          <p className="border-t border-line bg-danger-soft/40 px-5 py-2 text-xs text-danger">
            {actionError || camera.last_error}
          </p>
        )}
      </Card>

      {/* Stats */}
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon={<Database className="h-5 w-5" />}
          label="Frames indexed"
          value={compactNumber(totals.frames_total)}
          sub={`${compactNumber(totals.live_frames)} live · ${compactNumber(totals.upload_frames)} uploaded`}
        />
        <StatCard
          icon={<Boxes className="h-5 w-5" />}
          label="Objects detected"
          value={compactNumber(totals.detections_total)}
          tone="success"
          sub={topClass ? `mostly ${topClass.object_class}` : "waiting for detections"}
        />
        <StatCard
          icon={<Film className="h-5 w-5" />}
          label="Recordings"
          value={totals.recordings_total}
          tone="warn"
          sub={`${totals.recordings_ready} ready${totals.recordings_indexing ? ` · ${totals.recordings_indexing} indexing` : ""}`}
        />
        <StatCard
          icon={<Clock3 className="h-5 w-5" />}
          label="Footage indexed"
          value={formatClock(totals.indexed_video_seconds)}
          tone="neutral"
          sub="total duration of ready recordings"
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          {/* Live preview */}
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1.5 rounded-full bg-danger-soft px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-wider text-danger">
                  <span className="h-1.5 w-1.5 rounded-full bg-danger live-dot" /> Live
                </span>
                <span className="font-mono text-[11px] text-ink-muted">{camera.source_kind.toUpperCase()}</span>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={activeTracks.length ? "primary" : "neutral"}>{activeTracks.length} tracked</Badge>
                <Link href="/live" className="font-mono text-[11px] font-semibold text-primary hover:underline">
                  open full view
                </Link>
              </div>
            </div>
            <div className="relative aspect-video w-full bg-ink">
              {camera.running ? (
                <img
                  src={apiUrl("/api/camera/stream?overlay=true")}
                  alt="Live annotated camera preview"
                  className="h-full w-full object-contain"
                />
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-3 text-white/70">
                  <Wifi className="h-8 w-8" />
                  <p className="text-sm">Monitoring is stopped</p>
                  <button onClick={() => control.mutate("start")} className="rounded-xl bg-white px-4 py-2 text-xs font-semibold text-ink">
                    Start monitoring
                  </button>
                </div>
              )}
            </div>
            <div className="grid grid-cols-3 divide-x divide-line border-t border-line text-center">
              <div className="px-2 py-2.5">
                <p className="font-mono text-[10px] uppercase tracking-wide text-ink-muted">Frames received</p>
                <p className="font-mono text-sm font-semibold text-ink">{compactNumber(camera.frames_received)}</p>
              </div>
              <div className="px-2 py-2.5">
                <p className="font-mono text-[10px] uppercase tracking-wide text-ink-muted">Live frames indexed</p>
                <p className="font-mono text-sm font-semibold text-ink">{compactNumber(camera.frames_indexed)}</p>
              </div>
              <div className="px-2 py-2.5">
                <p className="font-mono text-[10px] uppercase tracking-wide text-ink-muted">Last frame</p>
                <p className="font-mono text-sm font-semibold text-ink">{camera.last_frame_at ? timeAgo(camera.last_frame_at) : "—"}</p>
              </div>
            </div>
          </Card>

          {/* Recent detections */}
          <Card className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-ink">Recent detections</h3>
                <p className="text-[11px] text-ink-muted">Latest tracked objects, newest first</p>
              </div>
              <Link href="/activity" className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline">
                Full activity <ArrowUpRight className="h-3 w-3" />
              </Link>
            </div>
            {data.recent_detections.length === 0 ? (
              <EmptyState
                title="No detections yet"
                message="Start monitoring or upload a video. YOLO detections will appear here with their tracking IDs."
                icon={<ScanEye className="h-7 w-7" />}
              />
            ) : (
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
                {data.recent_detections.map((detection) => (
                  <Link
                    key={detection.id}
                    href={`/activity?frame_id=${detection.frame_id}`}
                    className="group overflow-hidden rounded-xl border border-line bg-white transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-card"
                  >
                    <div className="relative aspect-[4/3] bg-surface-container">
                      {detection.thumbnail_url ? (
                        <img
                          src={apiUrl(detection.thumbnail_url)}
                          alt={`${detection.object_class} detection`}
                          className="absolute inset-0 h-full w-full object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <div className="absolute inset-0 flex items-center justify-center text-ink-muted">
                          <ScanEye className="h-5 w-5" />
                        </div>
                      )}
                      <span className="absolute left-1.5 top-1.5 rounded-md bg-ink/75 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase text-white">
                        {titleCase(detection.object_class)}
                        {detection.track_id ? ` #${detection.track_id}` : ""}
                      </span>
                    </div>
                    <div className="space-y-1 p-2">
                      <ScoreBar score={detection.confidence} />
                      <p className="truncate font-mono text-[9px] text-ink-muted">
                        {detection.source_type === "live" ? "live" : detection.recording_name} · {timeAgo(detection.captured_at)}
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Right rail */}
        <div className="space-y-4">
          <Card className="p-4">
            <div className="mb-3 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-bold text-ink">AI pipeline</h3>
              <span className="ml-auto font-mono text-[9px] uppercase tracking-wider text-ink-muted">
                {ai.embedder.device}
              </span>
            </div>
            <div className="space-y-2.5">
              <PipelineRow
                icon={<ScanEye className="h-4 w-4" />}
                label="Object detection"
                detail={`${ai.detector.model} · conf ${Math.round(ai.detector.confidence_threshold * 100)}%`}
                ready={ai.detector.ready}
              />
              <PipelineRow
                icon={<Layers className="h-4 w-4" />}
                label="ByteTrack tracking"
                detail={`${activeTracks.length} object${activeTracks.length === 1 ? "" : "s"} in current frame`}
                ready={online}
              />
              <PipelineRow
                icon={<Sparkles className="h-4 w-4" />}
                label="CLIP embeddings"
                detail={`${ai.embedder.model} · ${ai.embedder.dimension || "—"}-d · scene + crop`}
                ready={ai.embedder.loaded}
              />
              <PipelineRow
                icon={<Database className="h-4 w-4" />}
                label="ChromaDB vectors"
                detail={`${compactNumber(ai.vector_store.scenes)} scenes · ${compactNumber(ai.vector_store.objects)} objects`}
                ready
              />
            </div>
            <Link
              href="/search"
              className="mt-3 flex items-center justify-center gap-2 rounded-xl bg-primary-soft px-3 py-2 text-xs font-semibold text-primary transition hover:bg-primary hover:text-white"
            >
              <Sparkles className="h-3.5 w-3.5" /> Search indexed footage
            </Link>
          </Card>

          <Card className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-bold text-ink">Storage</h3>
              <span className="font-mono text-[10px] text-ink-muted">{storage.data_dir.split(/[\\/]/).pop()}</span>
            </div>
            <div className="mb-3 flex h-2 overflow-hidden rounded-full bg-surface-container">
              {storageRows.map((row) => (
                <div key={row.label} className={row.colour} style={{ width: `${percent(row.bytes)}%` }} />
              ))}
            </div>
            <ul className="space-y-1.5">
              {storageRows.map((row) => (
                <li key={row.label} className="flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1.5 text-ink-soft">
                    <span className={`h-1.5 w-1.5 rounded-full ${row.colour}`} /> {row.label}
                  </span>
                  <span className="font-mono text-ink-muted">
                    {Math.round(row.bytes / 1024 / 1024 * 10) / 10} MB
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 border-t border-line pt-2 text-[10px] text-ink-muted">
              {storage.thumbnails.count ?? 0} thumbnails · {storage.recordings.count ?? 0} video files
            </p>
          </Card>

          <Card className="p-4">
            <div className="mb-3 flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-bold text-ink">Recent activity</h3>
            </div>
            {data.activity.length === 0 ? (
              <p className="py-4 text-center text-xs text-ink-muted">Nothing has happened yet.</p>
            ) : (
              <ul className="space-y-2.5">
                {data.activity.slice(0, 8).map((item) => (
                  <li key={item.id} className="flex items-start gap-2">
                    <Badge tone={KIND_TONE[item.kind] || "neutral"}>{item.kind}</Badge>
                    <div className="min-w-0">
                      <p className="text-[11px] leading-snug text-ink-soft">{item.message}</p>
                      <p className="font-mono text-[9px] text-ink-muted">{timeAgo(item.created_at)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <p className="mt-4 flex items-center gap-2 text-[11px] text-ink-muted">
        <CirclePlay className="h-3.5 w-3.5" />
        Semantic search retrieves the closest frames by appearance. Actions are approximate visual evidence, not action recognition.
        {camera.last_frame_at && <span className="ml-auto hidden font-mono sm:block">last frame {formatDateTime(camera.last_frame_at)}</span>}
      </p>
    </AppShell>
  );
}

function PipelineRow({
  icon,
  label,
  detail,
  ready,
}: {
  icon: React.ReactNode;
  label: string;
  detail: string;
  ready: boolean;
}) {
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-line/70 bg-surface-low/60 px-2.5 py-2">
      <span className="mt-0.5 text-primary">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-[12px] font-semibold text-ink">{label}</p>
        <p className="truncate font-mono text-[10px] text-ink-muted">{detail}</p>
      </div>
      <span
        className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${ready ? "bg-emerald-500" : "bg-amber-400"}`}
        title={ready ? "ready" : "idle"}
      />
    </div>
  );
}
