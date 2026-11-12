"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Camera, Clock, Loader2, Play, ScanSearch, Search, ShieldCheck } from "lucide-react";

import { EmptyState, ErrorState, Field, PageHeader, ScoreBar, btnPrimary, inputCls } from "@/components/ui";
import { PlaybackModal } from "@/components/VideoPlayer";
import { api, errorMessage } from "@/lib/api";
import { MediaImg } from "@/lib/media";
import { formatDateTime, scorePercent } from "@/lib/format";
import type {
  Camera as CameraT,
  EntitySearchHit,
  EntitySearchResponse,
  TemporalSearchResponse,
  VideoSearchHit,
  VideoSearchResponse,
} from "@/types";

type Mode = "frames" | "entities" | "temporal";

const OBJECT_CLASSES = [
  "person",
  "forklift",
  "truck",
  "car",
  "bus",
  "bicycle",
  "motorcycle",
  "dog",
  "cat",
];

export default function SearchPage() {
  const [mode, setMode] = useState<Mode>("frames");
  const [query, setQuery] = useState("");
  const [cameraIds, setCameraIds] = useState<number[]>([]);
  const [zones, setZones] = useState<string[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [objectClass, setObjectClass] = useState("");
  const [results, setResults] = useState<VideoSearchResponse | EntitySearchResponse | TemporalSearchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<VideoSearchHit | EntitySearchHit | null>(null);

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: async () => (await api.get<CameraT[]>("/cameras")).data,
  });
  const zoneOptions = useMemo(() => [...new Set((cameras ?? []).map((c) => c.zone).filter(Boolean))], [cameras]);

  const runSearch = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    const common = {
      query: query.trim(),
      camera_ids: cameraIds.length ? cameraIds : null,
      zones: zones.length ? zones : null,
      start: start ? new Date(start).toISOString() : null,
      end: end ? new Date(end).toISOString() : null,
      top_k: 24,
    };
    try {
      const res =
        mode === "entities"
          ? await api.post<EntitySearchResponse>("/search/entities", { ...common, object_class: objectClass || null })
          : mode === "temporal"
            ? await api.post<TemporalSearchResponse>("/search/temporal", common)
            : await api.post<VideoSearchResponse>("/search/video", common);
      setResults(res.data);
    } catch (err) {
      setError(errorMessage(err, "Search failed"));
    } finally {
      setBusy(false);
    }
  };

  const frameHits = (results as VideoSearchResponse | null)?.hits ?? [];
  const entityHits = (results as EntitySearchResponse | null)?.hits ?? [];
  const temporalHits = (results as TemporalSearchResponse | null)?.hits ?? [];
  const total = mode === "entities" ? entityHits.length : mode === "temporal" ? temporalHits.length : frameHits.length;
  const temporalUsed = (results as TemporalSearchResponse | null)?.temporal_used ?? true;

  const switchMode = (m: Mode) => {
    if (m === mode) return;
    setMode(m);
    setResults(null);
  };

  return (
    <div>
      <PageHeader title="Natural Language Video Search" subtitle="Ask in plain English — CLIP finds matching frames, or YOLO-detected objects across cameras" />

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex w-fit rounded-lg bg-slate-100 p-1 text-sm">
          <button
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 transition ${mode === "frames" ? "bg-white font-medium text-blue-700 shadow-sm" : "text-slate-500"}`}
            onClick={() => switchMode("frames")}
          >
            <Search className="h-3.5 w-3.5" /> Frames
          </button>
          <button
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 transition ${mode === "entities" ? "bg-white font-medium text-blue-700 shadow-sm" : "text-slate-500"}`}
            onClick={() => switchMode("entities")}
          >
            <ScanSearch className="h-3.5 w-3.5" /> Objects
          </button>
          <button
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 transition ${mode === "temporal" ? "bg-white font-medium text-blue-700 shadow-sm" : "text-slate-500"}`}
            onClick={() => switchMode("temporal")}
          >
            <Clock className="h-3.5 w-3.5" /> Timeline
          </button>
        </div>

        <div className="flex gap-2">
          <input
            className={inputCls + " !py-3 text-base"}
            placeholder={
              mode === "entities"
                ? 'e.g. "person in a red jacket" or "forklift near the dock"'
                : mode === "temporal"
                  ? 'e.g. "forklift leaving the storage area" — matches whole 16s windows'
                  : 'e.g. "forklift near storage area" or "person at the loading dock after 6 PM"'
            }
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
          />
          <button className={btnPrimary + " shrink-0 !px-6"} onClick={runSearch} disabled={busy || !query.trim()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Search
          </button>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Cameras">
            <select
              className={inputCls}
              value={cameraIds.length === 1 ? cameraIds[0] : ""}
              onChange={(e) => {
                const v = e.target.value;
                setCameraIds(v ? [Number(v)] : []);
              }}
            >
              <option value="">All cameras</option>
              {(cameras ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Zones">
            <select
              className={inputCls}
              value={zones.length === 1 ? zones[0] : ""}
              onChange={(e) => setZones(e.target.value ? [e.target.value] : [])}
            >
              <option value="">All zones</option>
              {zoneOptions.map((z) => (
                <option key={z}>{z}</option>
              ))}
            </select>
          </Field>
          <Field label={mode === "entities" ? "Object class" : "From"}>
            {mode === "entities" ? (
              <select className={inputCls} value={objectClass} onChange={(e) => setObjectClass(e.target.value)}>
                <option value="">All objects</option>
                {OBJECT_CLASSES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="datetime-local"
                className={inputCls}
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            )}
          </Field>
          {mode !== "entities" && (
            <Field label="To">
              <input type="datetime-local" className={inputCls} value={end} onChange={(e) => setEnd(e.target.value)} />
            </Field>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-4">
          <ErrorState message={error} onRetry={runSearch} />
        </div>
      )}

      <div className="mt-6">
        {busy && <div className="flex justify-center py-16"><Loader2 className="h-8 w-8 animate-spin text-blue-600" /></div>}

        {!busy && results && total === 0 && (
          <EmptyState
            title="No matches found"
            message="Try different wording, widen the time range, or wait — frames are indexed every few seconds."
          />
        )}

        {!busy && results && total > 0 && (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <p className="text-sm text-slate-500">
                {total} match{total > 1 ? "es" : ""} for <span className="font-medium text-slate-700">“{results.query}”</span>
              </p>
              {mode === "temporal" && !temporalUsed && (
                <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700">
                  Temporal index not ready — showing frame-level matches
                </span>
              )}
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {(mode === "entities" ? entityHits : mode === "temporal" ? temporalHits : frameHits).map((hit) => (
                <div key={hit.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                  <button className="group relative block w-full bg-slate-950" onClick={() => setPlaying(hit)} title="Play clip">
                    <MediaImg path={hit.thumbnail_url} alt={hit.camera_name} className="h-40 w-full object-cover opacity-90 transition group-hover:opacity-100" />
                    <span className="absolute inset-0 flex items-center justify-center bg-slate-950/40 opacity-0 transition group-hover:opacity-100">
                      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-blue-600 shadow-lg">
                        <Play className="h-5 w-5 text-white" />
                      </span>
                    </span>
                    <span className="absolute bottom-2 left-2 rounded bg-slate-950/80 px-2 py-0.5 text-xs text-white">
                      {formatDateTime(hit.timestamp)}
                    </span>
                    {mode === "entities" && (
                      <span className="absolute right-2 top-2 rounded bg-blue-600/90 px-2 py-0.5 text-xs font-medium text-white">
                        {(hit as EntitySearchHit).object_class}
                      </span>
                    )}
                    {mode === "temporal" && (
                      <span className="absolute right-2 top-2 rounded bg-violet-600/90 px-2 py-0.5 text-xs font-medium text-white">
                        {(hit as TemporalSearchResponse["hits"][number]).frame_count} frames
                      </span>
                    )}
                  </button>
                  <div className="p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        <Camera className="mr-1 inline h-3.5 w-3.5 text-slate-400" />
                        {hit.camera_name}
                      </p>
                      <ScoreBar score={hit.score} />
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {hit.zone} · similarity {scorePercent(hit.score)}%
                      {mode === "entities" && (hit as EntitySearchHit).attrs && (
                        <span className="ml-1">
                          · {(hit as EntitySearchHit).attrs.color} · {(hit as EntitySearchHit).attrs.clothing}
                        </span>
                      )}
                    </p>
                    {mode === "temporal" && (
                      <p className="mt-2 rounded-lg bg-violet-50 px-2.5 py-1.5 text-xs text-violet-800">
                        <Clock className="mr-1 inline h-3 w-3" />
                        Window {(hit as TemporalSearchResponse["hits"][number]).window_start?.slice(0, 19).replace("T", " ")}
                        {" – "}
                        {(hit as TemporalSearchResponse["hits"][number]).window_end?.slice(0, 19).replace("T", " ")} UTC
                      </p>
                    )}
                    {mode === "entities" && (hit as EntitySearchHit).attrs?.ppe?.includes("safety helmet") && (
                      <p className="mt-2 flex items-center gap-1.5 rounded-lg bg-green-50 px-2.5 py-1.5 text-xs text-green-800">
                        <ShieldCheck className="h-3.5 w-3.5" /> {(hit as EntitySearchHit).attrs.ppe}
                      </p>
                    )}
                    {mode === "frames" && (
                      <p className="mt-2 rounded-lg bg-blue-50 px-2.5 py-1.5 text-xs text-blue-800">
                        {(hit as VideoSearchHit).explanation}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {!busy && !results && (
          <EmptyState
            title="Search across your cameras"
            message={
              mode === "entities"
                ? "YOLO detects people and vehicles in every sampled frame, CLIP embeds each object crop, and tracking groups them into stable identities. Search objects by appearance."
                : mode === "temporal"
                  ? "Recorded footage is re-embedded offline into 16-second temporal windows (nightly or on demand from the Cameras page). Search matches whole windows instead of single frames."
                  : "Every sampled frame is embedded with CLIP and stored in the vector database. Type what you want to find and press Search."
            }
            icon={mode === "entities" ? <ScanSearch className="h-8 w-8" /> : mode === "temporal" ? <Clock className="h-8 w-8" /> : <Search className="h-8 w-8" />}
          />
        )}
      </div>

      {playing && (
        <PlaybackModal
          src={playing.clip_url}
          offsetSeconds={playing.clip_offset_seconds}
          title={`${playing.camera_name} · ${playing.zone} · ${formatDateTime(playing.timestamp)}`}
          onClose={() => setPlaying(null)}
        />
      )}
    </div>
  );
}
