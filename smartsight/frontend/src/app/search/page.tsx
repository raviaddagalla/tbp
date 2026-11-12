"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarClock,
  Check,
  Clock3,
  Copy,
  Film,
  Layers,
  Loader2,
  Radar,
  ScanSearch,
  Search,
  SlidersHorizontal,
  Sparkles,
  Video,
  X,
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
  ScoreBar,
  Segmented,
  Skeleton,
  btnPrimary,
  btnSecondary,
  inputCls,
  selectCls,
} from "@/components/ui";
import { api, apiUrl, errorMessage } from "@/lib/api";
import { compactNumber, formatClock, formatDateTime, scorePercent, timeAgo, titleCase } from "@/lib/format";
import type { FrameDetail, Recording, SearchHit, SearchResponse } from "@/types";

type Mode = "both" | "scene" | "object";
type SourceFilter = "all" | "live" | "upload";
type TimeWindow = "all" | "1h" | "24h" | "7d";

const TIME_OPTIONS: { value: TimeWindow; label: string; hours: number }[] = [
  { value: "all", label: "All time", hours: 0 },
  { value: "1h", label: "Last hour", hours: 1 },
  { value: "24h", label: "Last 24 hours", hours: 24 },
  { value: "7d", label: "Last 7 days", hours: 168 },
];

export default function SmartSearchPage() {
  const [queryInput, setQueryInput] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [mode, setMode] = useState<Mode>("both");
  const [source, setSource] = useState<SourceFilter>("all");
  const [recordingId, setRecordingId] = useState("");
  const [objectClass, setObjectClass] = useState("");
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("all");
  const [limit, setLimit] = useState("12");
  const [minScore, setMinScore] = useState(0);
  const [showFilters, setShowFilters] = useState(false);
  const [selected, setSelected] = useState<SearchHit | null>(null);
  const [copied, setCopied] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);

  // Deep link: /search?source=live from the camera page.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sourceParam = params.get("source");
    if (sourceParam === "live" || sourceParam === "upload") setSource(sourceParam);

    const media = window.matchMedia("(min-width: 1280px)");
    const sync = () => setIsDesktop(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const examples = useQuery({
    queryKey: ["search-examples"],
    queryFn: async () => (await api.get<{ queries: string[] }>("/search/examples")).data,
    staleTime: Infinity,
  });
  const stats = useQuery({
    queryKey: ["search-stats"],
    queryFn: async () => (await api.get<{ scenes: number; objects: number }>("/search/stats")).data,
    refetchInterval: 15_000,
  });
  const recordings = useQuery({
    queryKey: ["recordings"],
    queryFn: async () => (await api.get<Recording[]>("/recordings")).data,
    staleTime: 20_000,
  });
  const classes = useQuery({
    queryKey: ["activity-classes"],
    queryFn: async () => (await api.get<{ classes: { object_class: string; count: number }[] }>("/activity?limit=1")).data,
    staleTime: 30_000,
  });

  const search = useMutation({
    mutationFn: async (query: string) => {
      const requested = TIME_OPTIONS.find((option) => option.value === timeWindow);
      const start = requested && requested.hours > 0 ? new Date(Date.now() - requested.hours * 3600_000).toISOString() : undefined;
      const response = await api.post<SearchResponse>("/search", {
        query,
        mode,
        limit: Number(limit),
        source_type: source === "all" ? undefined : source,
        recording_id: recordingId ? Number(recordingId) : undefined,
        object_class: objectClass || undefined,
        start,
        min_score: minScore,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setSubmitted(data.query);
      // On phones the inspector is a full-screen sheet, so open a result only
      // after the user taps it; on desktop show the top match in the right rail.
      const wide = typeof window !== "undefined" && window.matchMedia("(min-width: 1280px)").matches;
      setSelected(wide ? data.hits[0] ?? null : null);
    },
  });

  const runSearch = (text?: string) => {
    const value = (text ?? queryInput).trim();
    if (!value) return;
    setQueryInput(value);
    search.mutate(value);
  };

  // Deep link: /search?q=a+person+carrying+a+bag runs the search on load.
  const bootstrapped = useRef(false);
  useEffect(() => {
    if (bootstrapped.current) return;
    const initial = new URLSearchParams(window.location.search).get("q")?.trim();
    if (!initial) return;
    bootstrapped.current = true;
    setQueryInput(initial);
    search.mutate(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const results = search.data?.hits ?? [];
  const indexed = useMemo(
    () => ({
      scenes: stats.data?.scenes ?? 0,
      objects: stats.data?.objects ?? 0,
      total: (stats.data?.scenes ?? 0) + (stats.data?.objects ?? 0),
    }),
    [stats.data]
  );

  const frameDetail = useQuery({
    queryKey: ["frame-detail", selected?.frame_id],
    queryFn: async () => (await api.get<FrameDetail>(`/frames/${selected?.frame_id}`)).data,
    enabled: Boolean(selected?.frame_id),
    staleTime: 60_000,
  });

  const activeFilters =
    (source !== "all" ? 1 : 0) +
    (recordingId ? 1 : 0) +
    (objectClass ? 1 : 0) +
    (timeWindow !== "all" ? 1 : 0) +
    (minScore > 0 ? 1 : 0);

  return (
    <AppShell>
      <PageHeader
        eyebrow="AI retrieval"
        title="Smart search"
        subtitle="Describe what you remember seeing. CLIP matches scene frames and individual objects, then links every hit to its original moment."
        actions={
          <div className="flex items-center gap-2">
            <Badge tone="primary">{compactNumber(indexed.scenes)} scenes</Badge>
            <Badge tone="success">{compactNumber(indexed.objects)} objects</Badge>
          </div>
        }
      />

      {/* Search hero */}
      <Card className="overflow-hidden">
        <div className="bg-gradient-to-br from-primary via-indigo-600 to-indigo-500 p-4 sm:p-5">
          <div className="flex items-center gap-2 text-white/80">
            <Sparkles className="h-4 w-4" />
            <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em]">Natural language query</span>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              runSearch();
            }}
            className="mt-2 flex flex-col gap-2 sm:flex-row"
          >
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-muted" />
              <input
                value={queryInput}
                onChange={(event) => setQueryInput(event.target.value)}
                placeholder="e.g. a person carrying a red backpack"
                className="h-12 w-full rounded-xl border-0 bg-white pl-11 pr-10 text-sm text-ink shadow-float outline-none placeholder:text-ink-muted/70 focus:ring-2 focus:ring-white/60"
                maxLength={300}
              />
              {queryInput && (
                <button
                  type="button"
                  onClick={() => setQueryInput("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink"
                  aria-label="Clear query"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            <button type="submit" disabled={!queryInput.trim() || search.isPending} className="h-12 rounded-xl bg-white px-5 text-sm font-bold text-primary shadow-float transition hover:bg-white/90 disabled:opacity-60">
              {search.isPending ? <Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> : <Radar className="mr-1 inline h-4 w-4" />}
              Run search
            </button>
          </form>

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="mr-1 font-mono text-[10px] uppercase tracking-wider text-white/60">Try</span>
            {(examples.data?.queries ?? []).slice(0, 4).map((example) => (
              <button
                key={example}
                onClick={() => runSearch(example)}
                className="rounded-full border border-white/25 bg-white/10 px-2.5 py-1 text-[11px] font-medium text-white/90 transition hover:bg-white/20"
              >
                {example}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5">
          <Segmented
            value={mode}
            onChange={setMode}
            options={[
              { value: "both", label: "Both", icon: <Layers className="h-3 w-3" /> },
              { value: "scene", label: "Scene", icon: <Video className="h-3 w-3" /> },
              { value: "object", label: "Object", icon: <ScanSearch className="h-3 w-3" /> },
            ]}
          />
          <button
            onClick={() => setShowFilters((value) => !value)}
            className={`${btnSecondary} !px-3 !py-1.5 !text-[11px]`}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" /> Filters
            {activeFilters > 0 && (
              <span className="rounded-full bg-primary px-1.5 text-[10px] font-bold text-white">{activeFilters}</span>
            )}
          </button>
          <span className="ml-auto font-mono text-[10px] text-ink-muted">
            {search.isPending ? "encoding query…" : search.data ? `${results.length} matches` : "ready"}
          </span>
          {search.data && (
            <span className="hidden font-mono text-[10px] text-ink-muted sm:inline">
              {compactNumber(indexed.scenes)} scene + {compactNumber(indexed.objects)} object vectors scanned
            </span>
          )}
        </div>

        {showFilters && (
          <div className="grid gap-3 border-t border-line bg-surface-low/60 px-4 py-3 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Source">
              <select
                className={selectCls}
                value={source}
                onChange={(event) => {
                  setSource(event.target.value as SourceFilter);
                  if (event.target.value === "live") setRecordingId("");
                }}
              >
                <option value="all">Live + recordings</option>
                <option value="live">Live camera only</option>
                <option value="upload">Uploaded recordings only</option>
              </select>
            </Field>
            <Field label="Recording">
              <select className={selectCls} value={recordingId} onChange={(event) => setRecordingId(event.target.value)} disabled={source === "live"}>
                <option value="">Any recording</option>
                {(recordings.data ?? []).map((recording) => (
                  <option key={recording.id} value={recording.id}>
                    {recording.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Detected class">
              <select className={selectCls} value={objectClass} onChange={(event) => setObjectClass(event.target.value)}>
                <option value="">Any class</option>
                {(classes.data?.classes ?? []).map((item) => (
                  <option key={item.object_class} value={item.object_class}>
                    {titleCase(item.object_class)} ({item.count})
                  </option>
                ))}
                {["person", "car", "bus", "bicycle", "dog", "backpack"]
                  .filter((name) => !(classes.data?.classes ?? []).some((item) => item.object_class === name))
                  .map((name) => (
                    <option key={name} value={name}>
                      {titleCase(name)}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Time window" hint="Filters on when the frame was captured (live) or indexed (uploads)">
              <select className={selectCls} value={timeWindow} onChange={(event) => setTimeWindow(event.target.value as TimeWindow)}>
                {TIME_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Result limit">
              <select className={selectCls} value={limit} onChange={(event) => setLimit(event.target.value)}>
                <option value="12">12 results</option>
                <option value="24">24 results</option>
                <option value="48">48 results</option>
              </select>
            </Field>
            <Field label={`Minimum similarity — ${Math.round(minScore * 100)}%`}>
              <input
                type="range"
                min={0}
                max={0.45}
                step={0.01}
                value={minScore}
                onChange={(event) => setMinScore(Number(event.target.value))}
                className="mt-2 w-full accent-[#4648d4]"
              />
            </Field>
            <p className="text-[10px] leading-relaxed text-ink-muted sm:col-span-2 lg:col-span-3">
              Object-class filtering only applies to object matches. CLIP similarity is relative, so a 26% score can still be a strong match
              in a small index.
            </p>
          </div>
        )}
      </Card>

      {/* Results */}
      <div className="mt-4">
        {search.isPending ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((key) => (
              <Skeleton key={key} className="h-56" />
            ))}
          </div>
        ) : search.isError ? (
          <ErrorState message={errorMessage(search.error, "Search failed")} onRetry={() => runSearch(submitted || queryInput)} />
        ) : !search.data ? (
          <EmptyState
            title="Search your indexed footage"
            message={
              indexed.total > 0
                ? `${compactNumber(indexed.scenes)} scene frames and ${compactNumber(indexed.objects)} object crops are ready. Try "a person in a red shirt" or "a white car".`
                : "Nothing is indexed yet. Start the live camera or upload a recording, then come back."
            }
            icon={<Search className="h-7 w-7" />}
            action={
              indexed.total === 0 ? (
                <Link href="/recordings" className={btnPrimary}>
                  <Film className="h-4 w-4" /> Upload a video
                </Link>
              ) : (
                <button className={btnPrimary} onClick={() => runSearch(examples.data?.queries?.[0] || "a person")}>
                  <Sparkles className="h-4 w-4" /> Try an example
                </button>
              )
            }
          />
        ) : results.length === 0 ? (
          <EmptyState
            title="No matching frames"
            message="Try a simpler description (object + appearance), lower the similarity threshold, or widen the filters. CLIP retrieves appearance, not complex actions."
            icon={<ScanSearch className="h-7 w-7" />}
          />
        ) : (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <div>
              <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h2 className="text-sm font-bold text-ink">
                    {results.length} semantic match{results.length === 1 ? "" : "es"}
                  </h2>
                  <p className="text-[11px] text-ink-muted">
                    for &ldquo;{submitted}&rdquo; · {mode === "both" ? "scene + object" : mode} search
                  </p>
                </div>
                <span className="font-mono text-[10px] text-ink-muted">
                  ranked by CLIP cosine similarity
                </span>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                {results.map((hit) => (
                  <ResultCard key={`${hit.id}-${hit.match_type}`} hit={hit} active={selected?.id === hit.id} onSelect={() => setSelected(hit)} />
                ))}
              </div>
            </div>

            <div className="hidden xl:block">
              <div className="sticky top-20">
                <Inspector
                  hit={selected}
                  detail={frameDetail.data}
                  loadingDetail={frameDetail.isLoading}
                  copied={copied}
                  onCopy={async () => {
                    if (!selected) return;
                    const stamp = `${formatDateTime(selected.captured_at)} (${formatClock(selected.timestamp_seconds)})`;
                    try {
                      await navigator.clipboard.writeText(stamp);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1600);
                    } catch {
                      setCopied(false);
                    }
                  }}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Mobile inspector */}
      <Modal
        open={!isDesktop && Boolean(selected) && results.length > 0}
        onClose={() => setSelected(null)}
        title="Match inspector"
        subtitle={selected ? `${selected.match_type} match · ${scorePercent(selected.score)}% similarity` : undefined}
        wide
      >
        <div className="xl:hidden">
          <Inspector
            hit={selected}
            detail={frameDetail.data}
            loadingDetail={frameDetail.isLoading}
            copied={copied}
            onCopy={async () => {
              if (!selected) return;
              try {
                await navigator.clipboard.writeText(formatClock(selected.timestamp_seconds));
                setCopied(true);
                setTimeout(() => setCopied(false), 1600);
              } catch {
                setCopied(false);
              }
            }}
            compact
          />
        </div>
      </Modal>
    </AppShell>
  );
}

function ResultCard({ hit, active, onSelect }: { hit: SearchHit; active: boolean; onSelect: () => void }) {
  return (
    <button
      onClick={onSelect}
      className={`group overflow-hidden rounded-2xl border bg-white text-left transition hover:-translate-y-0.5 hover:shadow-card ${
        active ? "border-primary ring-2 ring-primary/20" : "border-line"
      }`}
    >
      <div className="relative aspect-video bg-ink">
        <img
          src={apiUrl(hit.frame_thumbnail_url || hit.thumbnail_url)}
          alt={`Frame match for ${hit.object_class || "scene"}`}
          className="absolute inset-0 h-full w-full object-cover"
          loading="lazy"
        />
        <span className="absolute left-2 top-2 rounded-md bg-white/90 px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wide text-ink">
          {hit.match_type}
        </span>
        <span className="absolute right-2 top-2 rounded-md bg-primary px-1.5 py-0.5 font-mono text-[10px] font-bold text-white">
          {scorePercent(hit.score)}%
        </span>
        <span className="absolute bottom-2 right-2 rounded-md bg-ink/80 px-1.5 py-0.5 font-mono text-[10px] text-white">
          {hit.source_type === "upload" ? formatClock(hit.timestamp_seconds) : timeAgo(hit.captured_at)}
        </span>
      </div>
      <div className="space-y-1.5 p-2.5">
        <div className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${hit.source_type === "live" ? "bg-rose-500" : "bg-primary"}`} />
          <p className="truncate text-[12px] font-semibold text-ink">
            {hit.source_type === "live" ? "ESP32 Live camera" : hit.recording_name}
          </p>
        </div>
        <p className="truncate font-mono text-[10px] text-ink-muted">
          {formatDateTime(hit.captured_at)}
          {hit.object_class ? ` · ${titleCase(hit.object_class)}` : ""}
          {hit.track_id ? ` #${hit.track_id}` : ""}
        </p>
        <div className="flex items-center justify-between gap-2">
          <ScoreBar score={hit.score} label={false} />
          <span className="font-mono text-[9px] text-ink-muted">
            {hit.detections.length} object{hit.detections.length === 1 ? "" : "s"}
          </span>
        </div>
      </div>
    </button>
  );
}

function Inspector({
  hit,
  detail,
  loadingDetail,
  copied,
  onCopy,
  compact = false,
}: {
  hit: SearchHit | null;
  detail?: FrameDetail;
  loadingDetail: boolean;
  copied: boolean;
  onCopy: () => void;
  compact?: boolean;
}) {
  if (!hit) {
    return (
      <Card className="p-5">
        <EmptyState title="Select a match" message="Pick a result to inspect the frame, its detections and the exact playback moment." icon={<ScanSearch className="h-6 w-6" />} />
      </Card>
    );
  }

  const width = detail?.width || 16;
  const height = detail?.height || 9;
  const matchedIndex =
    hit.match_type === "object"
      ? hit.detections.findIndex(
          (detection) =>
            detection.object_class === hit.object_class && (hit.track_id ? detection.track_id === hit.track_id : true)
        )
      : -1;

  return (
    <div className="space-y-3">
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-3 py-2">
          <span className="flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-primary">
            <Radar className="h-3.5 w-3.5" /> Match inspector
          </span>
          <Badge tone={hit.match_type === "scene" ? "primary" : "success"}>{hit.match_type}</Badge>
        </div>

        <div className="relative bg-ink" style={{ aspectRatio: `${width} / ${height}` }}>
          <img
            src={apiUrl(hit.frame_thumbnail_url || hit.thumbnail_url)}
            alt="Matched frame"
            className="absolute inset-0 h-full w-full object-contain"
          />
          {hit.detections.map((detection, index) => {
            const [x1, y1, x2, y2] = detection.bbox;
            const highlighted = index === matchedIndex;
            return (
              <div
                key={`${detection.track_id}-${index}`}
                className={`absolute rounded-[3px] border-2 ${
                  highlighted ? "border-white shadow-[0_0_0_2px_rgba(70,72,212,0.9)]" : "border-primary/70"
                }`}
                style={{
                  left: `${x1 * 100}%`,
                  top: `${y1 * 100}%`,
                  width: `${Math.max(0.5, (x2 - x1) * 100)}%`,
                  height: `${Math.max(0.5, (y2 - y1) * 100)}%`,
                }}
                title={`${detection.object_class} #${detection.track_id} · ${Math.round(detection.confidence * 100)}%`}
              >
                <span
                  className={`absolute -top-4 left-0 whitespace-nowrap rounded-sm px-1 py-0.5 font-mono text-[8px] font-bold text-white ${
                    highlighted ? "bg-primary" : "bg-ink/80"
                  }`}
                >
                  {titleCase(detection.object_class)}
                  {detection.track_id ? ` #${detection.track_id}` : ""} {Math.round(detection.confidence * 100)}%
                </span>
              </div>
            );
          })}
          {loadingDetail && <div className="absolute inset-0 animate-pulse bg-white/10" />}
        </div>

        <div className="space-y-2 p-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase tracking-wide text-ink-muted">Similarity</span>
            <span className="font-mono text-[13px] font-bold text-primary">{scorePercent(hit.score)}%</span>
          </div>
          <ScoreBar score={hit.score} label={false} />
          <dl className="space-y-1.5 pt-1 text-[11px]">
            <InspectorRow label="Source" value={hit.source_type === "live" ? "ESP32 Live camera" : hit.recording_name || "Recording"} />
            <InspectorRow label="Captured" value={formatDateTime(hit.captured_at)} />
            {hit.source_type === "upload" && <InspectorRow label="Footage time" value={formatClock(hit.timestamp_seconds)} mono />}
            <InspectorRow label="Frame" value={`#${hit.frame_number}`} mono />
            {hit.object_class && <InspectorRow label="Class" value={titleCase(hit.object_class)} />}
            {hit.track_id > 0 && <InspectorRow label="Tracking ID" value={`#${hit.track_id}`} mono />}
          </dl>
          <div className="flex flex-wrap gap-1.5 pt-1">
            <button onClick={onCopy} className={`${btnSecondary} !px-2.5 !py-1.5 !text-[11px]`}>
              {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
              {copied ? "Copied" : "Copy timestamp"}
            </button>
            <Link href={`/activity?frame_id=${hit.frame_id}`} className={`${btnSecondary} !px-2.5 !py-1.5 !text-[11px]`}>
              <CalendarClock className="h-3 w-3" /> Open in activity
            </Link>
          </div>
        </div>
      </Card>

      {hit.source_type === "upload" && hit.recording_id && (
        <Card className="overflow-hidden p-2">
          <p className="mb-1.5 flex items-center gap-1.5 px-1 font-mono text-[10px] uppercase tracking-wide text-ink-muted">
            <Clock3 className="h-3 w-3" /> Original recording · seeked to {formatClock(hit.timestamp_seconds)}
          </p>
          <VideoPlayer
            src={`/recordings/${hit.recording_id}/playback`}
            seekSeconds={hit.timestamp_seconds}
            title={hit.recording_name}
          />
        </Card>
      )}

      {hit.source_type === "live" && (
        <Card className="p-3">
          <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-ink-soft">
            <Video className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            Live hits are stored as timestamped snapshots, not continuous video, so this frame is the exact evidence.
            <Link href="/live" className="ml-1 font-semibold text-primary hover:underline">
              Open live
            </Link>
          </p>
        </Card>
      )}

      {!compact && hit.detections.length > 0 && (
        <Card className="p-3">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-wide text-ink-muted">
            Objects in this frame ({hit.detections.length})
          </p>
          <ul className="space-y-1.5">
            {hit.detections.map((detection, index) => (
              <li key={`${detection.track_id}-${index}`} className="flex items-center gap-2 rounded-lg border border-line px-2 py-1.5">
                {detection.thumbnail ? (
                  <img src={apiUrl(`/api/media/thumb/${detection.thumbnail}`)} alt="" className="h-8 w-8 rounded-md object-cover" />
                ) : (
                  <span className="h-8 w-8 rounded-md bg-surface-container" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[11px] font-semibold text-ink">
                    {titleCase(detection.object_class)}
                    {detection.track_id ? ` #${detection.track_id}` : ""}
                  </p>
                  <p className="font-mono text-[9px] text-ink-muted">
                    {Math.round(detection.confidence * 100)}% confidence{detection.colour ? ` · ${detection.colour}` : ""}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {matchedIndex >= 0 && !compact && (
        <p className="flex items-center gap-1 text-[10px] text-ink-muted">
          <ArrowRight className="h-3 w-3" /> Highlighted box is the object that matched your query.
        </p>
      )}
    </div>
  );
}

function InspectorRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-ink-muted">{label}</dt>
      <dd className={`min-w-0 break-all text-right font-medium text-ink-soft ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
