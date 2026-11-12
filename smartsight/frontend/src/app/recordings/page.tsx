"use client";

import React, { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Clock3,
  Film,
  Loader2,
  Play,
  RefreshCw,
  Trash2,
  UploadCloud,
  XCircle,
} from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { VideoPlayer } from "@/components/VideoPlayer";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageHeader,
  ProgressBar,
  Skeleton,
  StatusPill,
  btnDanger,
  btnPrimary,
  btnSecondary,
  inputCls,
  selectCls,
} from "@/components/ui";
import { api, apiUrl, errorMessage } from "@/lib/api";
import { compactNumber, formatClock, formatDateTime, titleCase } from "@/lib/format";
import type { Recording } from "@/types";

const SAMPLE_OPTIONS = [
  { value: "1", label: "1 frame/sec — lightest" },
  { value: "1.5", label: "1.5 frames/sec" },
  { value: "2", label: "2 frames/sec — default" },
  { value: "5", label: "5 frames/sec — detailed" },
];

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function RecordingsPage() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [sampleFps, setSampleFps] = useState("2");
  const [dragging, setDragging] = useState(false);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [notice, setNotice] = useState("");
  const [playing, setPlaying] = useState<Recording | null>(null);

  const recordings = useQuery({
    queryKey: ["recordings"],
    queryFn: async () => (await api.get<Recording[]>("/recordings")).data,
    refetchInterval: (query) => {
      const rows = query.state.data as Recording[] | undefined;
      const busy = rows?.some((row) => row.status === "queued" || row.status === "processing");
      return busy ? 2_000 : 8_000;
    },
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["recordings"] });
    queryClient.invalidateQueries({ queryKey: ["overview"] });
    queryClient.invalidateQueries({ queryKey: ["search-stats"] });
  };

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a video file first");
      const form = new FormData();
      form.append("file", file);
      form.append("name", name.trim() || file.name);
      form.append("sample_fps", sampleFps);
      setUploadPercent(0);
      const response = await api.post<Recording>("/recordings", form, {
        onUploadProgress: (event) => {
          if (event.total) setUploadPercent(Math.round((event.loaded / event.total) * 100));
        },
      });
      return response.data;
    },
    onSuccess: (recording) => {
      setFile(null);
      setName("");
      setUploadPercent(0);
      setNotice(`"${recording.name}" uploaded — indexing has started.`);
      if (fileInput.current) fileInput.current.value = "";
      invalidate();
    },
    onError: (err) => setNotice(errorMessage(err, "Upload failed")),
  });

  const reindex = useMutation({
    mutationFn: async (id: number) => (await api.post(`/recordings/${id}/reindex`)).data,
    onSuccess: invalidate,
    onError: (err) => setNotice(errorMessage(err, "Could not re-index")),
  });

  const cancel = useMutation({
    mutationFn: async (id: number) => (await api.post(`/recordings/${id}/cancel`)).data,
    onSuccess: invalidate,
    onError: (err) => setNotice(errorMessage(err, "Could not cancel indexing")),
  });

  const remove = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/recordings/${id}`)).data,
    onSuccess: () => {
      setNotice("Recording deleted");
      setPlaying(null);
      invalidate();
    },
    onError: (err) => setNotice(errorMessage(err, "Could not delete the recording")),
  });

  const rows = recordings.data ?? [];
  const totals = useMemo(
    () => ({
      videos: rows.length,
      frames: rows.reduce((sum, row) => sum + row.frames_indexed, 0),
      objects: rows.reduce((sum, row) => sum + row.objects_detected, 0),
    }),
    [rows]
  );

  const pickFile = (next: File | null) => {
    setFile(next);
    setNotice("");
    if (next && !name) setName(next.name.replace(/\.[^.]+$/, ""));
  };

  return (
    <AppShell>
      <PageHeader
        eyebrow="Library"
        title="Recordings"
        subtitle="Upload footage from your computer and SmartSight indexes it automatically — detection, tracking, CLIP embeddings and timestamps."
        actions={
          <div className="flex items-center gap-2">
            <Badge tone="neutral">{totals.videos} videos</Badge>
            <Badge tone="primary">{compactNumber(totals.frames)} frames</Badge>
            <Badge tone="success">{compactNumber(totals.objects)} objects</Badge>
          </div>
        }
      />

      {/* Upload */}
      <Card className="p-4 sm:p-5">
        <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const dropped = event.dataTransfer.files?.[0];
              if (dropped) pickFile(dropped);
            }}
            onClick={() => fileInput.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-4 py-7 text-center transition ${
              dragging ? "border-primary bg-primary-soft/50" : "border-line bg-surface-low/50 hover:border-primary/40 hover:bg-surface-low"
            }`}
          >
            <span className="rounded-2xl bg-white p-3 text-primary shadow-card">
              <UploadCloud className="h-6 w-6" />
            </span>
            <p className="text-sm font-semibold text-ink">
              {file ? file.name : "Drop a video here, or tap to choose"}
            </p>
            <p className="text-[11px] text-ink-muted">
              {file ? `${formatBytes(file.size)} · ready to upload` : "MP4, MOV, AVI, MKV, WebM (up to 2 GB)"}
            </p>
            <input
              ref={fileInput}
              type="file"
              accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm,.mp4,.mov,.avi,.mkv,.webm,.m4v"
              className="hidden"
              onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
            />
          </div>

          <div className="space-y-2.5">
            <Field label="Display name" hint="Optional — defaults to the file name">
              <input className={inputCls} value={name} onChange={(event) => setName(event.target.value)} placeholder="Front door clip" />
            </Field>
            <Field label="Sampling rate" hint="How many frames per second are analysed and indexed">
              <select className={selectCls} value={sampleFps} onChange={(event) => setSampleFps(event.target.value)}>
                {SAMPLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Field>
            <button
              onClick={() => upload.mutate()}
              disabled={!file || upload.isPending}
              className={`${btnPrimary} w-full`}
            >
              {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
              {upload.isPending ? `Uploading ${uploadPercent}%` : "Upload & index"}
            </button>
            {upload.isPending && <ProgressBar value={uploadPercent} />}
          </div>
        </div>
        {notice && (
          <p className="mt-3 flex items-start gap-1.5 rounded-xl bg-surface-low px-3 py-2 text-[11px] text-ink-soft">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" /> {notice}
          </p>
        )}
      </Card>

      <div className="mt-4">
        {recordings.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((key) => (
              <Skeleton key={key} className="h-72" />
            ))}
          </div>
        ) : recordings.isError ? (
          <ErrorState message={errorMessage(recordings.error, "Could not load recordings")} onRetry={() => recordings.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No recordings yet"
            message="Upload an MP4/MOV/AVI/MKV/WebM file above. It will be sampled, analysed with YOLO + ByteTrack, embedded with CLIP and made searchable."
            icon={<Film className="h-7 w-7" />}
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {rows.map((recording) => {
              const busy = recording.status === "queued" || recording.status === "processing";
              return (
                <Card key={recording.id} className="flex flex-col overflow-hidden">
                  <div className="relative aspect-video bg-ink">
                    {recording.thumbnail_url ? (
                      <img
                        src={apiUrl(recording.thumbnail_url)}
                        alt={recording.name}
                        className="absolute inset-0 h-full w-full object-cover"
                        loading="lazy"
                      />
                    ) : (
                      <div className="absolute inset-0 flex items-center justify-center text-white/40">
                        <Film className="h-8 w-8" />
                      </div>
                    )}
                    <div className="absolute inset-x-0 top-0 flex items-start justify-between p-2">
                      <StatusPill status={recording.status} />
                      <span className="rounded-md bg-ink/75 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white">
                        {formatClock(recording.duration_seconds)}
                      </span>
                    </div>
                    {recording.status === "ready" && (
                      <button
                        onClick={() => setPlaying(recording)}
                        className="absolute inset-0 flex items-center justify-center bg-ink/0 opacity-0 transition hover:bg-ink/30 hover:opacity-100"
                        aria-label={`Play ${recording.name}`}
                      >
                        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/95 text-primary shadow-float">
                          <Play className="ml-0.5 h-5 w-5" />
                        </span>
                      </button>
                    )}
                  </div>

                  <div className="flex flex-1 flex-col gap-2 p-3">
                    <div>
                      <h3 className="truncate text-[13px] font-bold text-ink">{recording.name}</h3>
                      <p className="truncate font-mono text-[10px] text-ink-muted">
                        {recording.original_name} · {formatDateTime(recording.created_at)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      <Badge tone="neutral">{recording.width ? `${recording.width}×${recording.height}` : "—"}</Badge>
                      <Badge tone="neutral">{recording.sample_fps} fps sampled</Badge>
                      <Badge tone="primary">{compactNumber(recording.frames_indexed)} frames</Badge>
                      <Badge tone="success">{compactNumber(recording.objects_detected)} objects</Badge>
                    </div>

                    {busy && (
                      <div>
                        <div className="mb-1 flex items-center justify-between font-mono text-[10px] text-ink-muted">
                          <span>{recording.status === "queued" ? "Waiting for the indexer…" : "Indexing frames…"}</span>
                          <span>{recording.progress}%</span>
                        </div>
                        <ProgressBar value={recording.progress} />
                      </div>
                    )}
                    {recording.status === "failed" && (
                      <p className="flex items-start gap-1 rounded-lg bg-danger-soft/50 px-2 py-1.5 text-[10px] text-danger">
                        <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" /> {recording.error || "Indexing failed"}
                      </p>
                    )}
                    {recording.status === "ready" && recording.error && (
                      <p className="flex items-start gap-1 rounded-lg bg-warn-soft/70 px-2 py-1.5 text-[10px] text-warn">
                        <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" /> {recording.error}
                      </p>
                    )}

                    <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t border-line pt-2">
                      <button
                        onClick={() => setPlaying(recording)}
                        disabled={recording.status !== "ready"}
                        className={`${btnSecondary} !px-2.5 !py-1.5 !text-[11px]`}
                      >
                        <Play className="h-3 w-3" /> Play
                      </button>
                      {busy ? (
                        <button
                          onClick={() => cancel.mutate(recording.id)}
                          disabled={cancel.isPending}
                          className={`${btnSecondary} !px-2.5 !py-1.5 !text-[11px]`}
                        >
                          <XCircle className="h-3 w-3" /> Cancel
                        </button>
                      ) : (
                        <button
                          onClick={() => reindex.mutate(recording.id)}
                          disabled={reindex.isPending}
                          className={`${btnSecondary} !px-2.5 !py-1.5 !text-[11px]`}
                          title="Delete its index and process the file again"
                        >
                          <RefreshCw className="h-3 w-3" /> Re-index
                        </button>
                      )}
                      <button
                        onClick={() => {
                          if (window.confirm(`Delete "${recording.name}" and all of its indexed frames?`)) {
                            remove.mutate(recording.id);
                          }
                        }}
                        disabled={remove.isPending || busy}
                        className={`${btnDanger} !ml-auto !px-2.5 !py-1.5 !text-[11px]`}
                        title={busy ? "Cancel indexing first" : "Delete recording"}
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-[11px] text-ink-muted">
        <Clock3 className="h-3.5 w-3.5" />
        Sampling {sampleFps} fps means a 60-second clip produces about {Math.round(Number(sampleFps) * 60)} searchable frames.
      </p>

      <Modal
        open={Boolean(playing)}
        onClose={() => setPlaying(null)}
        title={playing?.name || "Recording"}
        subtitle={playing ? `${formatDateTime(playing.created_at)} · ${titleCase(playing.status)}` : undefined}
        wide
      >
        {playing && (
          <div className="space-y-3">
            <VideoPlayer
              src={`/recordings/${playing.id}/playback`}
              title={`${playing.name} · ${playing.duration_seconds.toFixed(0)}s`}
            />
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Detail label="Duration" value={formatClock(playing.duration_seconds)} />
              <Detail label="Frames indexed" value={compactNumber(playing.frames_indexed)} />
              <Detail label="Objects" value={compactNumber(playing.objects_detected)} />
              <Detail label="Sampling" value={`${playing.sample_fps} fps`} />
            </div>
          </div>
        )}
      </Modal>
    </AppShell>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-low px-2.5 py-2">
      <p className="font-mono text-[9px] uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="font-mono text-[13px] font-semibold text-ink">{value}</p>
    </div>
  );
}
