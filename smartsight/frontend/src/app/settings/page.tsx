"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Camera,
  CheckCircle2,
  Cpu,
  Database,
  HardDrive,
  Info,
  Loader2,
  Play,
  PlugZap,
  RotateCcw,
  Save,
  Square,
  Wifi,
  XCircle,
  Zap,
} from "lucide-react";

import { AppShell } from "@/components/AppShell";
import {
  Badge,
  Card,
  ErrorState,
  Field,
  PageHeader,
  Skeleton,
  StatusPill,
  btnPrimary,
  btnSecondary,
  inputCls,
  selectCls,
} from "@/components/ui";
import { api, apiUrl, errorMessage } from "@/lib/api";
import { compactNumber, formatDateTime } from "@/lib/format";
import type { ProbeResult, SettingsResponse } from "@/types";

interface ConfigForm {
  stream_url: string;
  live_fps: string;
  index_interval_seconds: string;
  default_sample_fps: string;
  detector_enabled: boolean;
  auto_start: boolean;
}

const DEMO_URL = "sim://demo";

function configToForm(data: SettingsResponse): ConfigForm {
  return {
    stream_url: data.camera.stream_url,
    live_fps: String(data.camera.live_fps),
    index_interval_seconds: String(data.camera.index_interval_seconds),
    default_sample_fps: String(data.camera.default_sample_fps),
    detector_enabled: data.camera.detector_enabled,
    auto_start: data.camera.auto_start,
  };
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ConfigForm | null>(null);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState("");
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [validation, setValidation] = useState("");

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: async () => (await api.get<SettingsResponse>("/settings")).data,
  });

  useEffect(() => {
    if (settings.data && !dirty) setForm(configToForm(settings.data));
  }, [settings.data, dirty]);

  const update = (patch: Partial<ConfigForm>) => {
    setForm((current) => (current ? { ...current, ...patch } : current));
    setDirty(true);
    setMessage("");
  };

  const save = useMutation({
    mutationFn: async () => {
      if (!form) throw new Error("Settings are not loaded yet");
      let url = form.stream_url.trim();
      if (!url) throw new Error("Enter an ESP32-CAM stream URL");
      if (!/^(https?|rtsp|sim):\/\//i.test(url)) {
        url = `http://${url}`;
      }
      const response = await api.put<SettingsResponse>("/settings", {
        stream_url: url,
        live_fps: Number(form.live_fps),
        index_interval_seconds: Number(form.index_interval_seconds),
        default_sample_fps: Number(form.default_sample_fps),
        detector_enabled: form.detector_enabled,
        auto_start: form.auto_start,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setValidation("");
      setForm(configToForm(data));
      setDirty(false);
      setMessage("Settings saved. The camera service reloaded its configuration.");
      queryClient.setQueryData(["settings"], data);
      queryClient.invalidateQueries({ queryKey: ["camera-status"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
    onError: (err) => setValidation(errorMessage(err, "Could not save settings")),
  });

  const test = useMutation({
    mutationFn: async () => {
      let url = (form?.stream_url || "").trim();
      if (!url) throw new Error("Enter an ESP32-CAM IP address or stream URL first");
      if (!/^(https?|rtsp|sim):\/\//i.test(url)) {
        url = `http://${url}`;
      }
      const response = await api.post<ProbeResult>("/camera/test", { stream_url: url });
      return response.data;
    },
    onSuccess: (data) => {
      setProbe(data);
      if (data.ok && data.endpoint && data.endpoint !== form?.stream_url) {
        update({ stream_url: data.endpoint });
      }
    },
    onError: (err) => {
      setProbe(null);
      setValidation(errorMessage(err, "Connection test failed"));
    },
  });

  const control = useMutation({
    mutationFn: async (action: "start" | "stop") => (await api.post(`/camera/${action}`)).data,
    onSuccess: (_data, action) => {
      setMessage(action === "start" ? "Camera monitoring started." : "Camera monitoring stopped.");
      queryClient.invalidateQueries({ queryKey: ["camera-status"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
    onError: (err) => setValidation(errorMessage(err, "Could not change monitoring state")),
  });

  const storage = settings.data?.storage;
  const storageRows = useMemo(() => {
    if (!storage) return [];
    const rows = [
      { label: "Recordings", bucket: storage.recordings, colour: "bg-primary" },
      { label: "Vector store", bucket: storage.vectorstore, colour: "bg-indigo-400" },
      { label: "Thumbnails", bucket: storage.thumbnails, colour: "bg-emerald-400" },
      { label: "Snapshots", bucket: storage.snapshots, colour: "bg-amber-400" },
      { label: "Database", bucket: storage.database, colour: "bg-rose-400" },
    ];
    const total = rows.reduce((sum, row) => sum + row.bucket.bytes, 0) || 1;
    return rows.map((row) => ({ ...row, percent: Math.round((row.bucket.bytes / total) * 100) }));
  }, [storage]);

  if (settings.isLoading || !form) {
    return (
      <AppShell>
        <PageHeader title="Settings" subtitle="Camera, processing and storage configuration." />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
        </div>
      </AppShell>
    );
  }
  if (settings.isError || !settings.data) {
    return (
      <AppShell>
        <PageHeader title="Settings" />
        <ErrorState message={errorMessage(settings.error, "Could not load settings")} onRetry={() => settings.refetch()} />
      </AppShell>
    );
  }

  const data = settings.data;
  const runtime = data.camera_runtime;
  const simulated = form.stream_url === DEMO_URL;

  return (
    <AppShell>
      <PageHeader
        eyebrow="Configuration"
        title="Settings"
        subtitle="Point SmartSight at your ESP32-CAM, tune how much footage is processed, and inspect local storage."
        actions={
          <>
            <StatusPill status={runtime.status} />
            {runtime.running ? (
              <button onClick={() => control.mutate("stop")} disabled={control.isPending} className={btnSecondary}>
                <Square className="h-3.5 w-3.5" /> Stop camera
              </button>
            ) : (
              <button onClick={() => control.mutate("start")} disabled={control.isPending} className={btnPrimary}>
                <Play className="h-3.5 w-3.5" /> Start camera
              </button>
            )}
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-4">
          {/* Camera connection */}
          <Card className="p-4 sm:p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-bold text-ink">
                <Camera className="h-4 w-4 text-primary" /> ESP32-CAM connection
              </h2>
              {simulated && <Badge tone="warn">simulated source</Badge>}
            </div>

            <Field
              label="Stream URL"
              hint="The board's webserver endpoint, e.g. http://192.168.1.50:81/stream (MJPEG) or http://192.168.1.50:81/snapshot"
            >
              <input
                className={`${inputCls} font-mono`}
                value={form.stream_url}
                onChange={(event) => {
                  update({ stream_url: event.target.value });
                  setProbe(null);
                }}
                placeholder="http://192.168.1.50:81/stream"
                spellCheck={false}
              />
            </Field>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button type="button" onClick={() => update({ stream_url: "http://192.168.0.132:81/stream" })} className={chipCls}>
                Current ESP32 (:81/stream)
              </button>
              <button type="button" onClick={() => update({ stream_url: "http://192.168.0.132/capture" })} className={chipCls}>
                Current ESP32 (/capture)
              </button>
              <button type="button" onClick={() => update({ stream_url: "http://192.168.0.132" })} className={chipCls}>
                Auto-probe :81/stream
              </button>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button onClick={() => test.mutate()} disabled={test.isPending} className={btnSecondary}>
                {test.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
                {test.isPending ? "Probing endpoint…" : "Test connection"}
              </button>
              <span className="text-[11px] text-ink-muted">
                Tries MJPEG, snapshot and (if given) RTSP readers, then reports what the camera actually speaks.
              </span>
            </div>

            {probe && (
              <div
                className={`mt-3 rounded-xl border p-3 ${
                  probe.ok ? "border-success/30 bg-success-soft/40" : "border-danger/30 bg-danger-soft/40"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className={`flex items-center gap-1.5 text-[12px] font-semibold ${probe.ok ? "text-success" : "text-danger"}`}>
                    {probe.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                    {probe.ok ? `Connected · ${probe.kind.toUpperCase()} reader` : "Connection failed"}
                  </p>
                  {probe.ok && probe.endpoint && probe.endpoint !== form.stream_url && (
                    <button
                      type="button"
                      onClick={() => update({ stream_url: probe.endpoint })}
                      className="rounded-lg bg-primary px-2.5 py-1 text-[11px] font-semibold text-white shadow-xs hover:bg-primary-hover"
                    >
                      Apply {probe.endpoint}
                    </button>
                  )}
                </div>
                <p className="mt-1 break-all font-mono text-[10px] text-ink-soft">{probe.endpoint || form.stream_url}</p>
                <p className="mt-0.5 text-[11px] text-ink-soft">{probe.detail}</p>
                {probe.preview_data_url && (
                  <img
                    src={probe.preview_data_url}
                    alt="Camera test frame"
                    className="mt-2 max-h-44 rounded-lg border border-line object-contain"
                  />
                )}
              </div>
            )}
          </Card>

          {/* Processing */}
          <Card className="p-4 sm:p-5">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-ink">
              <Zap className="h-4 w-4 text-primary" /> Live processing
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Live capture rate" hint="Frames per second read from the camera (0.5 – 10)">
                <input
                  type="number"
                  min={0.5}
                  max={10}
                  step={0.5}
                  className={inputCls}
                  value={form.live_fps}
                  onChange={(event) => update({ live_fps: event.target.value })}
                />
              </Field>
              <Field label="Embed every N seconds" hint="One frame per interval gets CLIP scene + object embeddings">
                <input
                  type="number"
                  min={1}
                  max={120}
                  step={1}
                  className={inputCls}
                  value={form.index_interval_seconds}
                  onChange={(event) => update({ index_interval_seconds: event.target.value })}
                />
              </Field>
              <Field label="Default upload sampling" hint="Used when a video is uploaded without an explicit rate">
                <select
                  className={selectCls}
                  value={form.default_sample_fps}
                  onChange={(event) => update({ default_sample_fps: event.target.value })}
                >
                  <option value="1">1 frame/sec</option>
                  <option value="1.5">1.5 frames/sec</option>
                  <option value="2">2 frames/sec</option>
                  <option value="5">5 frames/sec</option>
                </select>
              </Field>
              <div className="space-y-2 pt-1">
                <Toggle
                  label="YOLO detection"
                  description="Draw boxes and store detections (disable to only embed frames)"
                  checked={form.detector_enabled}
                  onChange={(value) => update({ detector_enabled: value })}
                />
                <Toggle
                  label="Auto-start monitoring"
                  description="Start the camera reader when the backend boots"
                  checked={form.auto_start}
                  onChange={(value) => update({ auto_start: value })}
                />
              </div>
            </div>
          </Card>

          {validation && (
            <p className="flex items-start gap-1.5 rounded-xl border border-danger/30 bg-danger-soft/50 px-3 py-2 text-[12px] text-danger">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0" /> {validation}
            </p>
          )}
          {message && (
            <p className="flex items-start gap-1.5 rounded-xl border border-success/30 bg-success-soft/50 px-3 py-2 text-[12px] text-success">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> {message}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => save.mutate()} disabled={!dirty || save.isPending} className={btnPrimary}>
              {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {dirty ? "Save changes" : "Saved"}
            </button>
            <button
              onClick={() => {
                setForm(configToForm(data));
                setDirty(false);
                setValidation("");
                setMessage("");
                setProbe(null);
              }}
              disabled={!dirty}
              className={btnSecondary}
            >
              <RotateCcw className="h-4 w-4" /> Discard
            </button>
            <span className="text-[11px] text-ink-muted">
              Changing the source or rates restarts the camera thread.
            </span>
          </div>
        </div>

        {/* Right rail */}
        <div className="space-y-4">
          <Card className="p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-ink">
              <Wifi className="h-4 w-4 text-primary" /> Camera runtime
            </h2>
            <dl className="space-y-2 text-[11px]">
              <InfoRow label="State" value={runtime.status} />
              <InfoRow label="Source kind" value={runtime.source_kind} />
              <InfoRow label="Resolution" value={runtime.frame_width ? `${runtime.frame_width}×${runtime.frame_height}` : "—"} />
              <InfoRow label="Measured" value={`${runtime.measured_fps.toFixed(1)} fps`} />
              <InfoRow label="Frames received" value={compactNumber(runtime.frames_received)} />
              <InfoRow label="Frames indexed" value={compactNumber(runtime.frames_indexed)} />
              <InfoRow label="Last frame" value={runtime.last_frame_at ? formatDateTime(runtime.last_frame_at) : "—"} />
            </dl>
            {runtime.last_error && (
              <p className="mt-2 rounded-lg bg-danger-soft/60 px-2 py-1.5 text-[10px] text-danger">{runtime.last_error}</p>
            )}
            <Link href="/live" className="mt-3 block text-center font-mono text-[10px] font-semibold uppercase tracking-wider text-primary hover:underline">
              open live camera →
            </Link>
          </Card>

          <Card className="p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-ink">
              <Cpu className="h-4 w-4 text-primary" /> Models
            </h2>
            <div className="space-y-2">
              <ModelRow
                name="YOLO detector"
                detail={`${data.ai.detector.model} · conf ${Math.round(data.ai.detector.confidence_threshold * 100)}%`}
                ready={data.ai.detector.ready}
              />
              <ModelRow
                name="CLIP embedder"
                detail={`${data.ai.embedder.model} · ${data.ai.embedder.dimension || "—"}-d · ${data.ai.embedder.device}`}
                ready={data.ai.embedder.loaded}
              />
              <ModelRow
                name="ChromaDB"
                detail={`${compactNumber(data.ai.vector_store.scenes)} scenes · ${compactNumber(data.ai.vector_store.objects)} objects`}
                ready
              />
            </div>
            <p className="mt-2 text-[10px] leading-relaxed text-ink-muted">
              Models load once per backend process. YOLOv8n keeps CPU inference usable on a laptop; no paid APIs are involved.
            </p>
          </Card>

          <Card className="p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-ink">
              <HardDrive className="h-4 w-4 text-primary" /> Storage
            </h2>
            {storage && (
              <>
                <div className="mb-2 flex h-2 overflow-hidden rounded-full bg-surface-container">
                  {storageRows.map((row) => (
                    <div key={row.label} className={row.colour} style={{ width: `${Math.max(row.percent, 1)}%` }} />
                  ))}
                </div>
                <ul className="space-y-1.5">
                  {storageRows.map((row) => (
                    <li key={row.label} className="flex items-center justify-between text-[11px]">
                      <span className="flex items-center gap-1.5 text-ink-soft">
                        <span className={`h-1.5 w-1.5 rounded-full ${row.colour}`} /> {row.label}
                      </span>
                      <span className="font-mono text-ink-muted">{row.bucket.human}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 break-all border-t border-line pt-2 font-mono text-[9px] text-ink-muted">{storage.data_dir}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Badge tone="neutral">upload cap {storage.max_upload_mb} MB</Badge>
                  <Badge tone="neutral">index cap {compactNumber(storage.index_frame_cap)} frames</Badge>
                </div>
              </>
            )}
            <p className="mt-2 text-[10px] leading-relaxed text-ink-muted">
              Everything is local: SQLite metadata, JPEG thumbnails, uploaded files and the Chroma vector store.
            </p>
          </Card>

          {data.server.indexer.active !== null && (
            <Card className="p-4">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-ink">
                <Database className="h-4 w-4 text-primary" /> Indexer
              </h2>
              <p className="text-[11px] text-ink-soft">
                Processing recording #{data.server.indexer.active}
                {data.server.indexer.queued.length > 0 ? ` · ${data.server.indexer.queued.length} queued` : ""}
              </p>
            </Card>
          )}

          <Card className="p-4">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-ink">
              <Info className="h-4 w-4 text-primary" /> About
            </h2>
            <p className="text-[11px] leading-relaxed text-ink-soft">
              SmartSight v1.0 · one ESP32-CAM + uploaded video, YOLOv8n detection, ByteTrack IDs, CLIP semantic search and timestamp playback.
              Built for a single-user local deployment.
            </p>
            <p className="mt-2 font-mono text-[9px] text-ink-muted">
              {data.server.app_name} · {data.server.vector_store_dir}
            </p>
          </Card>
        </div>
      </div>

    </AppShell>
  );
}

const chipCls =
  "rounded-full border border-line bg-surface-low px-2.5 py-1 text-[10px] font-semibold text-ink-soft transition hover:border-primary/40 hover:text-primary";

function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex w-full items-start gap-2.5 rounded-xl border border-line bg-surface-low/50 px-3 py-2 text-left">
      <span
        className={`mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition ${checked ? "bg-primary" : "bg-surface-high"}`}
      >
        <span className={`h-4 w-4 rounded-full bg-white shadow transition ${checked ? "translate-x-4" : ""}`} />
      </span>
      <span>
        <span className="block text-[12px] font-semibold text-ink">{label}</span>
        <span className="block text-[10px] leading-snug text-ink-muted">{description}</span>
      </span>
    </button>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-ink-muted">{label}</dt>
      <dd className="min-w-0 break-all text-right font-mono text-ink-soft">{value}</dd>
    </div>
  );
}

function ModelRow({ name, detail, ready }: { name: string; detail: string; ready: boolean }) {
  return (
    <div className="rounded-xl border border-line px-2.5 py-2">
      <div className="flex items-center justify-between">
        <p className="text-[12px] font-semibold text-ink">{name}</p>
        <span className={`h-1.5 w-1.5 rounded-full ${ready ? "bg-emerald-500" : "bg-amber-400"}`} />
      </div>
      <p className="truncate font-mono text-[10px] text-ink-muted">{detail}</p>
    </div>
  );
}
