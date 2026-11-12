"use client";

import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Link2, MapPin, Save, Upload, X } from "lucide-react";

import { EmptyState, ErrorState, PageHeader, Spinner, btnPrimary, btnSecondary, inputCls } from "@/components/ui";
import { api, authedUrl, errorMessage } from "@/lib/api";
import { useAuth, hasRole } from "@/lib/auth";
import type { AdjacencyEdge, Camera } from "@/types";

type Pins = Record<string, { x: number; y: number }>;

const MAX_H = 480;
const MAX_W = 720;

function fitInside(w: number, h: number) {
  const scale = Math.min(1, MAX_W / w, MAX_H / h);
  return { w: Math.round(w * scale), h: Math.round(h * scale) };
}

export default function FloorplanPage() {
  const { user } = useAuth();
  const isAdmin = hasRole(user, ["admin"]);
  const qc = useQueryClient();

  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const [draftPins, setDraftPins] = useState<Pins | null>(null);
  const [placing, setPlacing] = useState<number | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [draftEdges, setDraftEdges] = useState<AdjacencyEdge[] | null>(null);
  const [fromId, setFromId] = useState<number | "">("");
  const [toId, setToId] = useState<number | "">("");
  const [minSec, setMinSec] = useState(10);
  const [maxSec, setMaxSec] = useState(300);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  const { data: cameras, isLoading: loadingCams, error: camError } = useQuery({
    queryKey: ["cameras"],
    queryFn: async () => (await api.get<Camera[]>("/cameras")).data,
  });

  const { data: adjacency } = useQuery({
    queryKey: ["adjacency"],
    queryFn: async () => (await api.get<AdjacencyEdge[]>("/cameras/adjacency")).data,
  });

  const { data: floorplan } = useQuery({
    queryKey: ["floorplan"],
    queryFn: async () => {
      const res = await api.get<{ id: number | null; name: string; pins: Pins; image_url: string }>("/floorplan");
      return res.data;
    },
  });

  // Local edits are layered on top of server data; drafts reset after save.
  const pins = draftPins ?? floorplan?.pins ?? {};
  const edges = draftEdges ?? adjacency ?? [];

  useEffect(() => {
    if (floorplan?.image_url) {
      authedUrl(floorplan.image_url)
        .then((url) => {
          setImageUrl(url);
          const img = new Image();
          img.onload = () => setImgSize(fitInside(img.naturalWidth, img.naturalHeight));
          img.src = url;
        })
        .catch(() => setImageUrl(null));
    }
  }, [floorplan]);

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", "Site Floor Plan");
      return (await api.post("/floorplan", fd)).data as { image_url: string; pins: Pins };
    },
    onSuccess: (data) => {
      setError(null);
      setDraftPins(null);
      if (data.image_url) {
        authedUrl(data.image_url).then((url) => {
          setImageUrl(url);
          const img = new Image();
          img.onload = () => setImgSize(fitInside(img.naturalWidth, img.naturalHeight));
          img.src = url;
        });
      }
      qc.invalidateQueries({ queryKey: ["floorplan"] });
    },
    onError: (err) => setError(errorMessage(err, "Upload failed")),
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      await api.put("/cameras/adjacency", {
        edges: edges.map((e) => ({
          from_camera_id: e.from_camera_id,
          to_camera_id: e.to_camera_id,
          expected_transit_seconds_min: e.expected_transit_seconds_min,
          expected_transit_seconds_max: e.expected_transit_seconds_max,
          direction_label: e.direction_label ?? "",
        })),
      });
      await api.put("/floorplan/pins", { pins });
      qc.invalidateQueries({ queryKey: ["adjacency"] });
      qc.invalidateQueries({ queryKey: ["floorplan"] });
    },
    onSuccess: () => {
      setDraftPins(null);
      setDraftEdges(null);
      setSaved("Calibration saved — cross-camera stitching now uses these edges.");
      setTimeout(() => setSaved(null), 4000);
    },
    onError: (err) => setError(errorMessage(err, "Save failed")),
  });

  const addEdge = () => {
    if (!fromId || !toId || fromId === toId) return;
    if (edges.some((e) => e.from_camera_id === fromId && e.to_camera_id === toId)) return;
    setDraftEdges((prev) => [
      ...(prev ?? adjacency ?? []),
      {
        from_camera_id: fromId,
        to_camera_id: toId,
        from_camera_name: cameras?.find((c) => c.id === fromId)?.name ?? "",
        to_camera_name: cameras?.find((c) => c.id === toId)?.name ?? "",
        expected_transit_seconds_min: minSec,
        expected_transit_seconds_max: maxSec,
        direction_label: "",
      },
    ]);
    setFromId("");
    setToId("");
  };

  const placePin = (e: React.MouseEvent<HTMLDivElement>) => {
    if (placing === null || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * 10000) / 100;
    const y = Math.round(((e.clientY - rect.top) / rect.height) * 10000) / 100;
    setDraftPins((prev) => ({ ...(prev ?? pins), [String(placing)]: { x, y } }));
    setPlacing(null);
  };

  const onDragMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragId || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * 10000) / 100;
    const y = Math.round(((e.clientY - rect.top) / rect.height) * 10000) / 100;
    setDraftPins((prev) => ({ ...(prev ?? pins), [dragId]: { x: Math.min(100, Math.max(0, x)), y: Math.min(100, Math.max(0, y)) } }));
  };

  if (loadingCams) return <Spinner label="Loading cameras…" />;
  if (camError) return <ErrorState message="Could not load cameras" />;

  const placed = new Set(Object.keys(pins));
  const unplaced = (cameras ?? []).filter((c) => !placed.has(String(c.id)));
  const camById = new Map((cameras ?? []).map((c) => [c.id, c]));

  return (
    <div>
      <PageHeader
        title="Site Floor Plan"
        subtitle="Drag cameras onto the floor plan and draw directed adjacency edges with expected transit windows — cross-camera trails only follow these edges."
        actions={
          <button className={btnPrimary} onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            {saveMutation.isPending ? "Saving…" : <><Save className="h-4 w-4" /> Save calibration</>}
          </button>
        }
      />

      {error && (
        <div className="mb-4">
          <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
        </div>
      )}
      {saved && (
        <div className="mb-4">
          <p className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            <Check className="h-4 w-4" /> {saved}
          </p>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">
                {imageUrl ? (floorplan?.name ?? "Floor plan") : "No floor plan uploaded"}
              </h2>
              {isAdmin && (
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
                  <Upload className="h-3.5 w-3.5" />
                  Upload image
                  <input
                    type="file"
                    accept=".jpg,.jpeg,.png,.webp"
                    className="hidden"
                    disabled={uploadMutation.isPending}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) uploadMutation.mutate(f);
                    }}
                  />
                </label>
              )}
            </div>

            {!imageUrl ? (
              <EmptyState
                title="No floor plan yet"
                message={isAdmin ? "Upload a JPG/PNG/WebP site map to place cameras on it." : "An admin needs to upload the site floor plan."}
                icon={<MapPin className="h-10 w-10" />}
              />
            ) : (
              <div
                ref={canvasRef}
                className="relative mx-auto touch-none select-none"
                style={imgSize ? { width: imgSize.w, height: imgSize.h } : { aspectRatio: "4/3", width: "100%" }}
                onClick={placePin}
                onPointerMove={onDragMove}
                onPointerUp={() => setDragId(null)}
              >
                <img src={imageUrl} alt="Floor plan" className="h-full w-full rounded-lg object-contain ring-1 ring-slate-200" draggable={false} />
                {(cameras ?? []).map((c) => {
                  const p = pins[String(c.id)];
                  if (!p) return null;
                  const cam = camById.get(c.id);
                  return (
                    <div
                      key={c.id}
                      className="absolute -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none active:cursor-grabbing"
                      style={{ left: `${p.x}%`, top: `${p.y}%` }}
                      onPointerDown={(e) => {
                        e.stopPropagation();
                        if (isAdmin) setDragId(String(c.id));
                      }}
                    >
                      <div className="flex flex-col items-center">
                        <span className={`flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-bold text-white shadow ${cam?.status === "online" ? "bg-emerald-600" : "bg-slate-500"}`}>
                          {c.id}
                        </span>
                        <span className="mt-0.5 rounded bg-slate-900/70 px-1 py-px text-[9px] font-medium text-white">{c.name}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {isAdmin && imageUrl && unplaced.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-slate-500">Place camera:</span>
                {unplaced.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setPlacing(c.id)}
                    className={`rounded-full border px-3 py-1 text-xs font-medium ${
                      placing === c.id ? "border-blue-500 bg-blue-600 text-white" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    {c.id} · {c.name}
                  </button>
                ))}
                {placing !== null && (
                  <button className="text-xs text-slate-400 underline" onClick={() => setPlacing(null)}>
                    cancel
                  </button>
                )}
              </div>
            )}
            {placing !== null && (
              <p className="mt-2 text-xs text-blue-600">Click anywhere on the map to drop camera {placing}.</p>
            )}
          </div>
        </div>

        <div className="space-y-5">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Link2 className="h-4 w-4 text-blue-600" /> Adjacency edges
            </h2>
            {!isAdmin && <p className="mb-3 text-xs text-slate-400">Read-only — only admins can edit the calibration.</p>}
            <div className="mb-3 space-y-2">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span className="w-12">From</span>
                <select className={inputCls + " py-1.5"} value={fromId} onChange={(e) => setFromId(Number(e.target.value))} disabled={!isAdmin}>
                  <option value="">—</option>
                  {(cameras ?? []).map((c) => (
                    <option key={c.id} value={c.id}>{c.id} · {c.name}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span className="w-12">To</span>
                <select className={inputCls + " py-1.5"} value={toId} onChange={(e) => setToId(Number(e.target.value))} disabled={!isAdmin}>
                  <option value="">—</option>
                  {(cameras ?? []).map((c) => (
                    <option key={c.id} value={c.id}>{c.id} · {c.name}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span className="w-12">Transit</span>
                <input type="number" min={1} max={86400} className={inputCls + " py-1.5"} value={minSec} onChange={(e) => setMinSec(Number(e.target.value))} disabled={!isAdmin} />
                <span>–</span>
                <input type="number" min={1} max={86400} className={inputCls + " py-1.5"} value={maxSec} onChange={(e) => setMaxSec(Number(e.target.value))} disabled={!isAdmin} />
                <span>s</span>
              </div>
              <button className={btnSecondary + " w-full justify-center py-1.5 text-xs"} onClick={addEdge} disabled={!isAdmin || !fromId || !toId || fromId === toId}>
                Add directed edge
              </button>
            </div>
            <div className="space-y-1.5">
              {edges.length === 0 && <p className="text-xs text-slate-400">No edges yet. Trails stay within a single camera until edges exist.</p>}
              {edges.map((e, i) => (
                <div key={i} className="flex items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs">
                  <span className="font-medium text-slate-700">{e.from_camera_id} → {e.to_camera_id}</span>
                  <span className="text-slate-400">
                    {e.expected_transit_seconds_min}s–{e.expected_transit_seconds_max}s
                  </span>
                  <span className="ml-auto truncate text-[10px] text-slate-400">
                    {e.from_camera_name} → {e.to_camera_name}
                  </span>
                  {isAdmin && (
                    <button
                      className="rounded p-0.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                      onClick={() => setDraftEdges((prev) => (prev ?? adjacency ?? []).filter((_, j) => j !== i))}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold text-slate-900">How stitching works</h2>
            <ul className="space-y-1.5 text-xs leading-relaxed text-slate-500">
              <li>· ReID appearance embedding + predicted transit window + adjacency = trail score.</li>
              <li>· Trails on an alert show per-step confidence; low-confidence hops are omitted.</li>
              <li>· Calibration is global — one site plan, applied to every camera.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
