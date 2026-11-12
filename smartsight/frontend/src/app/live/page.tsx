"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Camera,
  CameraOff,
  Cctv,
  Crosshair,
  Expand,
  Layers,
  Play,
  Radio,
  Search,
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
  Segmented,
  Skeleton,
  StatusPill,
  btnPrimary,
  btnSecondary,
} from "@/components/ui";
import { api, apiUrl, errorMessage } from "@/lib/api";
import { compactNumber, formatClock, timeAgo, titleCase } from "@/lib/format";
import type { CameraStats, LiveDetectionsResponse } from "@/types";

interface CameraStatusResponse extends CameraStats {
  config: { stream_url: string; live_fps: number; index_interval_seconds: number; auto_start: boolean };
}

interface SnapshotResponse {
  ok: boolean;
  filename: string;
  url: string;
  captured_at: string;
  bytes: number;
}

export default function LiveCameraPage() {
  const queryClient = useQueryClient();
  const panelRef = useRef<HTMLDivElement>(null);
  const [overlay, setOverlay] = useState(true);
  const [snapshot, setSnapshot] = useState<SnapshotResponse | null>(null);
  const [message, setMessage] = useState("");
  const [quickUrl, setQuickUrl] = useState("");

  const status = useQuery({
    queryKey: ["camera-status"],
    queryFn: async () => (await api.get<CameraStatusResponse>("/camera/status")).data,
    refetchInterval: 3_000,
  });

  useEffect(() => {
    if (status.data?.source_url) {
      setQuickUrl(status.data.source_url);
    }
  }, [status.data?.source_url]);

  const updateUrl = useMutation({
    mutationFn: async (targetUrl: string) => {
      let target = targetUrl.trim();
      if (!target) throw new Error("Enter an ESP32 camera URL");
      if (!/^(https?|rtsp|sim):\/\//i.test(target)) {
        target = `http://${target}`;
      }
      return (await api.put("/camera/config", { stream_url: target })).data;
    },
    onSuccess: () => {
      setMessage("Camera URL updated and monitoring started");
      queryClient.invalidateQueries({ queryKey: ["camera-status"] });
      queryClient.invalidateQueries({ queryKey: ["camera-detections"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
    onError: (err) => setMessage(errorMessage(err, "Failed to update camera URL")),
  });
  const detections = useQuery({
    queryKey: ["camera-detections"],
    queryFn: async () => (await api.get<LiveDetectionsResponse>("/camera/detections")).data,
    refetchInterval: 1_500,
  });

  const control = useMutation({
    mutationFn: async (action: "start" | "stop") => (await api.post(`/camera/${action}`)).data,
    onSuccess: (_data, action) => {
      setMessage(action === "start" ? "Monitoring started" : "Monitoring stopped");
      queryClient.invalidateQueries({ queryKey: ["camera-status"] });
      queryClient.invalidateQueries({ queryKey: ["camera-detections"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (err) => setMessage(errorMessage(err, "Could not change monitoring state")),
  });

  const capture = useMutation({
    mutationFn: async () =>
      (await api.post<SnapshotResponse>(`/camera/snapshot?overlay=${overlay ? "true" : "false"}`)).data,
    onSuccess: (data) => {
      setSnapshot(data);
      setMessage("Snapshot saved to data/snapshots");
    },
    onError: (err) => setMessage(errorMessage(err, "Snapshot failed — is a frame available?")),
  });

  const fullscreen = async () => {
    try {
      if (panelRef.current?.requestFullscreen) {
        await panelRef.current.requestFullscreen();
      } else {
        setMessage("Fullscreen is not supported in this browser");
      }
    } catch {
      setMessage("Fullscreen was blocked by the browser");
    }
  };

  if (status.isLoading) {
    return (
      <AppShell>
        <PageHeader title="Live camera" subtitle="ESP32-CAM stream with detection overlays." />
        <Skeleton className="h-[420px]" />
      </AppShell>
    );
  }
  if (status.isError || !status.data) {
    return (
      <AppShell>
        <PageHeader title="Live camera" />
        <ErrorState message={errorMessage(status.error, "Could not reach the camera service")} onRetry={() => status.refetch()} />
      </AppShell>
    );
  }

  const camera = status.data;
  const online = camera.status === "online";
  const activeTracks = detections.data?.detections ?? [];

  return (
    <AppShell>
      <PageHeader
        eyebrow="Monitoring"
        title="Live camera"
        subtitle={
          camera.source_kind === "simulated"
            ? "Simulated demo feed — no ESP32 hardware is attached. Configure the camera in Settings to use your board."
            : "Live ESP32-CAM feed with YOLO boxes, labels, confidence scores and ByteTrack IDs drawn on the server."
        }
        actions={
          <>
            <StatusPill status={camera.status} />
            {camera.source_kind === "simulated" && <Badge tone="warn">simulated</Badge>}
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-3">
          <Card className="overflow-hidden">
            {/* stream header */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1.5 rounded-full bg-danger px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-wider text-white">
                  <span className="h-1.5 w-1.5 rounded-full bg-white live-dot" /> {online ? "Live" : "Offline"}
                </span>
                <span className="font-mono text-[11px] text-ink-soft">ESP32-CAM · MAIN</span>
                {online && (
                  <span className="hidden font-mono text-[10px] text-ink-muted sm:inline">
                    {camera.frame_width}×{camera.frame_height} · {camera.measured_fps.toFixed(1)} fps
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[10px] uppercase tracking-wide text-ink-muted">Overlay</span>
                <Segmented
                  size="sm"
                  value={overlay ? "on" : "off"}
                  onChange={(value) => setOverlay(value === "on")}
                  options={[
                    { value: "on", label: "Detections" },
                    { value: "off", label: "Raw" },
                  ]}
                />
              </div>
            </div>

            {/* video panel */}
            <div ref={panelRef} className="group relative bg-ink">
              <div className="relative aspect-video w-full">
                {online ? (
                  <img
                    src={apiUrl(`/api/camera/stream?overlay=${overlay ? "true" : "false"}`)}
                    alt="ESP32-CAM live stream"
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <div className="flex h-full flex-col items-center justify-center gap-3 bg-[#171e2b] p-6 text-white/70">
                    <Wifi className="h-9 w-9 text-white/40" />
                    <p className="text-sm font-medium text-white">{camera.status === "reconnecting" ? "Connecting to ESP32-CAM…" : "Camera is offline"}</p>
                    <p className="max-w-md text-center font-mono text-[11px] text-white/40">{camera.last_error || camera.source_url}</p>

                    <div className="mt-2 flex w-full max-w-md items-center gap-2">
                      <input
                        type="text"
                        value={quickUrl}
                        onChange={(e) => setQuickUrl(e.target.value)}
                        placeholder="http://10.63.89.95:81/stream"
                        className="flex-1 rounded-xl border border-white/20 bg-black/40 px-3 py-1.5 font-mono text-xs text-white placeholder-white/30 focus:border-primary focus:outline-none"
                      />
                      <button
                        onClick={() => updateUrl.mutate(quickUrl)}
                        disabled={updateUrl.isPending}
                        className="rounded-xl bg-primary px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-primary-hover disabled:opacity-50"
                      >
                        {updateUrl.isPending ? "Connecting…" : "Connect"}
                      </button>
                    </div>

                    <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
                      <button onClick={() => control.mutate("start")} disabled={control.isPending} className={btnPrimary}>
                        <Play className="h-4 w-4" /> Start monitoring
                      </button>
                      <Link href="/settings" className={btnSecondary}>
                        Configure in Settings
                      </Link>
                    </div>
                  </div>
                )}

                {/* HUD chips */}
                {online && (
                  <>
                    <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap items-center gap-1.5">
                      <span className="hud-blur rounded-lg px-2 py-1 font-mono text-[10px] font-semibold text-ink">
                        {camera.source_kind === "simulated" ? "SIMULATED SOURCE" : "ESP32-CAM"}
                      </span>
                      <span className="hud-blur rounded-lg px-2 py-1 font-mono text-[10px] text-ink">
                        {overlay ? `${activeTracks.length} tracked` : "raw feed"}
                      </span>
                      {camera.index_pending && (
                        <span className="rounded-lg bg-primary/90 px-2 py-1 font-mono text-[10px] font-semibold text-white">
                          embedding…
                        </span>
                      )}
                    </div>
                    <div className="pointer-events-none absolute bottom-3 left-3 hud-blur rounded-lg px-2 py-1 font-mono text-[10px] text-ink">
                      {camera.last_frame_at ? `FRAME ${timeAgo(camera.last_frame_at)}` : "NO FRAME YET"}
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* controls */}
            <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
              {camera.running ? (
                <button onClick={() => control.mutate("stop")} disabled={control.isPending} className={btnSecondary}>
                  <Square className="h-3.5 w-3.5" /> Stop
                </button>
              ) : (
                <button onClick={() => control.mutate("start")} disabled={control.isPending} className={btnPrimary}>
                  <Play className="h-3.5 w-3.5" /> Start monitoring
                </button>
              )}
              <button onClick={() => capture.mutate()} disabled={!online || capture.isPending} className={btnSecondary}>
                <Camera className="h-4 w-4" /> Capture snapshot
              </button>
              <button onClick={fullscreen} className={btnSecondary}>
                <Expand className="h-4 w-4" /> Fullscreen
              </button>
              <Link href="/search?source=live" className={btnSecondary}>
                <Search className="h-4 w-4" /> Search this camera
              </Link>
              {snapshot && (
                <a
                  href={apiUrl(snapshot.url)}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-auto inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-primary hover:underline"
                >
                  open saved snapshot ↗
                </a>
              )}
            </div>
            {message && <p className="border-t border-line bg-surface-low px-4 py-2 text-[11px] text-ink-soft">{message}</p>}
          </Card>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label="Frames received" value={compactNumber(camera.frames_received)} />
            <Metric label="Frames indexed" value={compactNumber(camera.frames_indexed)} />
            <Metric label="Objects detected" value={compactNumber(camera.objects_detected)} />
            <Metric label="Last frame" value={camera.last_frame_at ? timeAgo(camera.last_frame_at) : "—"} />
          </div>
        </div>

        {/* Right rail */}
        <div className="space-y-3">
          <Card className="p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-bold text-ink">
                <Crosshair className="h-4 w-4 text-primary" /> Active tracklets
              </h3>
              <Badge tone={activeTracks.length ? "primary" : "neutral"}>{activeTracks.length} in frame</Badge>
            </div>
            <p className="mb-3 text-[11px] text-ink-muted">
              Live objects get a ByteTrack ID. Each sampled frame stores that ID with its crop embedding.
            </p>
            {activeTracks.length === 0 ? (
              <EmptyState
                title={online ? "No objects in view" : "Camera offline"}
                message={online ? "YOLO has not detected anything in the current frame." : "Start monitoring to receive frames."}
                icon={<CameraOff className="h-6 w-6" />}
              />
            ) : (
              <ul className="space-y-2">
                {activeTracks.map((track, index) => (
                  <li key={`${track.track_id}-${index}`} className="rounded-xl border border-line bg-surface-low/50 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 text-[12px] font-semibold text-ink">
                        <span className="rounded-md bg-primary-soft px-1.5 py-0.5 font-mono text-[9px] font-bold text-primary">
                          #{track.track_id || "—"}
                        </span>
                        {titleCase(track.object_class)}
                      </span>
                      <span className="font-mono text-[10px] text-ink-muted">{Math.round(track.confidence * 100)}%</span>
                    </div>
                    <div className="mt-1.5">
                      <ScoreBar score={track.confidence} label={false} />
                    </div>
                    <p className="mt-1 font-mono text-[9px] text-ink-muted">
                      box {track.bbox.map((v) => v.toFixed(2)).join(", ")}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="p-4">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-ink">
              <Radio className="h-4 w-4 text-primary" /> Connection
            </h3>
            <dl className="space-y-2 text-[11px]">
              <Row label="Endpoint" value={camera.source_url} mono />
              <Row label="Reader" value={camera.source_kind} />
              <Row label="State" value={camera.status} />
              <Row label="Processed FPS" value={`${camera.measured_fps.toFixed(1)} fps`} />
              <Row label="Index every" value={`${camera.index_interval_seconds}s`} />
              <Row label="Resolution" value={camera.frame_width ? `${camera.frame_width}×${camera.frame_height}` : "—"} />
              <Row label="Detection" value={camera.detector_enabled ? "YOLOv8n" : "disabled"} />
            </dl>
            {camera.last_error && <p className="mt-2 rounded-lg bg-danger-soft/60 px-2 py-1.5 text-[10px] text-danger">{camera.last_error}</p>}
            <Link href="/settings" className="mt-3 flex items-center justify-center gap-1.5 rounded-xl border border-line px-3 py-2 text-[11px] font-semibold text-ink-soft hover:border-primary/40 hover:text-primary">
              <Cctv className="h-3.5 w-3.5" /> Configure ESP32-CAM
            </Link>
          </Card>

          <Card className="bg-primary p-4 text-white">
            <h3 className="flex items-center gap-2 text-sm font-bold">
              <Layers className="h-4 w-4" /> What gets indexed
            </h3>
            <p className="mt-1.5 text-[11px] leading-relaxed text-white/80">
              Every {camera.index_interval_seconds}s one frame is embedded: the full scene plus a crop of each tracked object. Those vectors are
              searchable with plain language.
            </p>
            <p className="mt-2 font-mono text-[10px] text-white/60">
              {formatClock(camera.frames_indexed * camera.measured_fps)} of processed footage indexed
            </p>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card className="px-3 py-2.5">
      <p className="font-mono text-[9px] uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="font-mono text-[15px] font-semibold text-ink">{value}</p>
    </Card>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-ink-muted">{label}</dt>
      <dd className={`min-w-0 break-all text-right text-ink-soft ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
