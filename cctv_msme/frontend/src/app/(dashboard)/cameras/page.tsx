"use client";

import React, { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Film, Pencil, Plus, ScanSearch, ShieldAlert, Trash2 } from "lucide-react";

import { EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusBadge, btnDanger, btnPrimary, btnSecondary, inputCls } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth, hasRole } from "@/lib/auth";
import { MediaImg } from "@/lib/media";
import { useWs } from "@/lib/ws";
import { compactNumber, timeAgo } from "@/lib/format";
import type { Camera as CameraT } from "@/types";

const ZONE_OPTIONS = ["Loading Dock", "Logistics", "Warehouse", "Production", "Machine Zone", "Packaging", "Quality", "General"];

interface CameraForm {
  name: string;
  rtsp_url: string;
  zone: string;
  location_label: string;
  sample_interval_seconds: number;
  clip_segment_seconds: number;
  retention_hours: number;
  anomaly_enabled: boolean;
  detector_enabled: boolean;
}

type SourceKind = "rtsp" | "usb" | "sim";

const SIM_SCENES = ["loading_dock", "storage", "machine_zone", "office", "packaging"];

const emptyForm: CameraForm = {
  name: "",
  rtsp_url: "",
  zone: "Logistics",
  location_label: "",
  sample_interval_seconds: 0.2,
  clip_segment_seconds: 30,
  retention_hours: 72,
  anomaly_enabled: false,
  detector_enabled: true,
};

function CameraFormModal({
  open,
  onClose,
  camera,
}: {
  open: boolean;
  onClose: () => void;
  camera?: CameraT | null;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<CameraForm>(
    camera
      ? {
          name: camera.name,
          rtsp_url: camera.rtsp_url,
          zone: camera.zone,
          location_label: camera.location_label,
          sample_interval_seconds: camera.sample_interval_seconds,
          clip_segment_seconds: camera.clip_segment_seconds,
          retention_hours: camera.retention_hours,
          anomaly_enabled: camera.anomaly_enabled,
          detector_enabled: camera.detector_enabled,
        }
      : emptyForm
  );
  const [sourceKind, setSourceKind] = useState<SourceKind>("rtsp");
  const [usbIndex, setUsbIndex] = useState(0);
  const [simScene, setSimScene] = useState(SIM_SCENES[0]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        ...form,
        rtsp_url:
          sourceKind === "usb"
            ? `usb://${usbIndex}`
            : sourceKind === "sim"
              ? `sim://${simScene}`
              : form.rtsp_url,
      };
      if (camera) {
        await api.patch(`/cameras/${camera.id}`, payload);
      } else {
        await api.post("/cameras", { ...payload, is_active: true });
      }
      await qc.invalidateQueries({ queryKey: ["cameras"] });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const set = (k: keyof CameraForm, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Modal open={open} onClose={onClose} title={camera ? `Edit camera — ${camera.name}` : "Add camera"}>
      <div className="space-y-4">
        <Field label="Camera name" hint={camera ? undefined : "e.g. Loading Dock - CAM01"}>
          <input className={inputCls} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Loading Dock - CAM01" />
        </Field>
        <Field label="Source type">
          <div className="flex gap-2">
            {(
              [
                ["rtsp", "RTSP / IP camera"],
                ["usb", "Webcam / USB"],
                ["sim", "Simulated (demo)"],
              ] as [SourceKind, string][]
            ).map(([kind, label]) => (
              <button
                key={kind}
                onClick={() => setSourceKind(kind)}
                className={
                  "flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition " +
                  (sourceKind === kind
                    ? "border-blue-600 bg-blue-50 text-blue-700"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50")
                }
              >
                {label}
              </button>
            ))}
          </div>
        </Field>
        {sourceKind === "rtsp" ? (
          <Field
            label="RTSP URL"
            hint={camera ? undefined : "Real CCTV: rtsp://user:pass@camera-ip:554/stream1"}
          >
            <input className={inputCls} value={form.rtsp_url} onChange={(e) => set("rtsp_url", e.target.value)} placeholder="rtsp://user:pass@10.0.0.5:554/stream1" />
          </Field>
        ) : sourceKind === "usb" ? (
          <Field label="USB camera index" hint="0 = first camera found by the OS (webcam), 1 = first external USB camera, etc.">
            <input
              type="number"
              min={0}
              className={inputCls}
              value={usbIndex}
              onChange={(e) => setUsbIndex(Number(e.target.value))}
            />
          </Field>
        ) : (
          <Field label="Simulated scene">
            <select className={inputCls} value={simScene} onChange={(e) => setSimScene(e.target.value)}>
              {SIM_SCENES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Zone">
            <select className={inputCls} value={form.zone} onChange={(e) => set("zone", e.target.value)}>
              {ZONE_OPTIONS.map((z) => (
                <option key={z}>{z}</option>
              ))}
            </select>
          </Field>
          <Field label="Location label">
            <input className={inputCls} value={form.location_label} onChange={(e) => set("location_label", e.target.value)} placeholder="Gate 2" />
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Sample every (s)" hint="0.2 = 5 fps">
            <input type="number" min={0.1} max={600} step={0.1} className={inputCls} value={form.sample_interval_seconds} onChange={(e) => set("sample_interval_seconds", Number(e.target.value))} />
          </Field>
          <Field label="Clip length (s)">
            <input type="number" min={10} max={300} className={inputCls} value={form.clip_segment_seconds} onChange={(e) => set("clip_segment_seconds", Number(e.target.value))} />
          </Field>
          <Field label="Retention (h)">
            <input type="number" min={1} className={inputCls} value={form.retention_hours} onChange={(e) => set("retention_hours", Number(e.target.value))} />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.anomaly_enabled}
            onChange={(e) => set("anomaly_enabled", e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-blue-600"
          />
          <ShieldAlert className="h-4 w-4 text-amber-500" /> Zero-shot safety anomaly detection (no helmet / smoke / restricted zone / spill)
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.detector_enabled}
            onChange={(e) => set("detector_enabled", e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-blue-600"
          />
          <ScanSearch className="h-4 w-4 text-blue-500" /> Object detection & tracking (people / vehicles — powers object search)
        </label>
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button className={btnSecondary} onClick={onClose}>
            Cancel
          </button>
          <button
            className={btnPrimary}
            onClick={save}
            disabled={busy || !form.name || (sourceKind === "rtsp" && !form.rtsp_url)}
          >
            {camera ? "Save changes" : "Add camera"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function CameraCard({ camera, isAdmin, onEdit }: { camera: CameraT; isAdmin: boolean; onEdit: () => void }) {
  const qc = useQueryClient();
  const wsStatus = useWs().cameraStatus[camera.id];
  const status = wsStatus?.status || camera.status;
  const isFileSource = camera.rtsp_url.startsWith("file://");

  const toggleActive = async () => {
    await api.patch(`/cameras/${camera.id}`, { is_active: !camera.is_active });
    await qc.invalidateQueries({ queryKey: ["cameras"] });
  };
  const remove = async () => {
    if (!window.confirm(`Delete camera "${camera.name}"? Indexed frames stay in search results.`)) return;
    await api.delete(`/cameras/${camera.id}`);
    await qc.invalidateQueries({ queryKey: ["cameras"] });
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="relative bg-slate-950">
        {camera.is_active && !isFileSource ? (
          <MediaImg path={`/api/streams/preview/${camera.id}`} alt={camera.name} className="h-44 w-full object-cover" />
        ) : (
          <div className="flex h-44 flex-col items-center justify-center gap-1 bg-slate-900 text-slate-500">
            {isFileSource ? (
              <>
                <Film className="h-6 w-6" />
                <span className="text-xs">Uploaded footage</span>
              </>
            ) : (
              <span className="text-sm">Camera deactivated</span>
            )}
          </div>
        )}
        <div className="absolute left-2 top-2">
          <StatusBadge status={status} />
        </div>
        {isFileSource && (
          <span className="absolute right-2 top-2 rounded-full bg-violet-500/90 px-2 py-0.5 text-[10px] font-semibold text-white" title="Uploaded video file">
            FILE
          </span>
        )}
        {camera.anomaly_enabled && (
          <span className="absolute right-2 top-8 rounded-full bg-amber-500/90 px-2 py-0.5 text-[10px] font-semibold text-white" title="Anomaly detection on">
            <ShieldAlert className="mr-0.5 inline h-3 w-3" /> A.I. watch
          </span>
        )}
        {camera.detector_enabled && (
          <span className="absolute right-2 top-16 rounded-full bg-blue-500/90 px-2 py-0.5 text-[10px] font-semibold text-white" title="Object detection & tracking on">
            <ScanSearch className="mr-0.5 inline h-3 w-3" /> Tracking
          </span>
        )}
      </div>
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate font-semibold text-slate-900">{camera.name}</p>
            <p className="text-xs text-slate-500">
              {camera.zone}
              {camera.location_label ? ` · ${camera.location_label}` : ""}
            </p>
          </div>
          <span className="shrink-0 rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">
            {compactNumber(camera.frames_indexed)} frames
          </span>
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
          <span>Last seen {timeAgo(camera.last_seen_at)}</span>
          <span className="truncate pl-2 font-mono" title={camera.rtsp_url}>
            {camera.rtsp_url.slice(0, 30)}
          </span>
        </div>
        {camera.status !== "online" && camera.last_error && (
          <p className="mt-2 truncate rounded bg-amber-50 px-2 py-1 text-xs text-amber-700" title={camera.last_error}>
            {camera.last_error}
          </p>
        )}
        {isAdmin && (
          <div className="mt-3 flex gap-2 border-t border-slate-100 pt-3">
            <button className={btnSecondary + " !px-3 !py-1.5 text-xs"} onClick={onEdit}>
              <Pencil className="h-3.5 w-3.5" /> Edit
            </button>
            <button className={btnSecondary + " !px-3 !py-1.5 text-xs"} onClick={toggleActive}>
              {camera.is_active ? "Deactivate" : "Activate"}
            </button>
            <button className={btnDanger + " !px-3 !py-1.5 text-xs ml-auto"} onClick={remove}>
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function UploadFootageModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState({ name: "", zone: "General", location_label: "", anomaly_enabled: false });
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", form.name || file.name);
      fd.append("zone", form.zone);
      fd.append("location_label", form.location_label);
      fd.append("anomaly_enabled", String(form.anomaly_enabled));
      await api.post("/cameras/upload", fd);
      await qc.invalidateQueries({ queryKey: ["cameras"] });
      setForm({ name: "", zone: "General", location_label: "", anomaly_enabled: false });
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onClose();
    } catch (err) {
      setError(errorMessage(err, "Upload failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Upload CCTV footage">
      <div className="space-y-4">
        <p className="text-sm text-slate-500">
          Upload a recorded video (MP4, MOV, AVI, MKV, WebM — up to 2 GB). It is analysed at 2 frames per second and becomes searchable
          like a live camera.
        </p>
        <Field label="Footage file">
          <input
            ref={fileRef}
            type="file"
            accept=".mp4,.m4v,.mov,.avi,.mkv,.webm"
            className={inputCls}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
        <Field label="Camera name">
          <input className={inputCls} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Dock footage - 03 Aug" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Zone">
            <select className={inputCls} value={form.zone} onChange={(e) => setForm((f) => ({ ...f, zone: e.target.value }))}>
              {ZONE_OPTIONS.map((z) => (
                <option key={z}>{z}</option>
              ))}
            </select>
          </Field>
          <Field label="Location label">
            <input className={inputCls} value={form.location_label} onChange={(e) => setForm((f) => ({ ...f, location_label: e.target.value }))} placeholder="Gate 2" />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.anomaly_enabled}
            onChange={(e) => setForm((f) => ({ ...f, anomaly_enabled: e.target.checked }))}
            className="h-4 w-4 rounded border-slate-300 text-blue-600"
          />
          <ShieldAlert className="h-4 w-4 text-amber-500" /> Safety anomaly detection on this footage
        </label>
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button className={btnSecondary} onClick={onClose}>Cancel</button>
          <button className={btnPrimary} onClick={upload} disabled={busy || !file}>
            {busy ? "Uploading…" : "Upload & analyse"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export default function CamerasPage() {
  const { user } = useAuth();
  const isAdmin = hasRole(user, ["admin"]);
  const [modalOpen, setModalOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState<CameraT | null>(null);

  const { data: cameras, isLoading, error, refetch } = useQuery({
    queryKey: ["cameras"],
    queryFn: async () => (await api.get<CameraT[]>("/cameras")).data,
    refetchInterval: 15_000,
  });

  if (isLoading) return <Spinner label="Loading cameras…" />;
  if (error) return <ErrorState message="Could not load cameras" onRetry={() => refetch()} />;

  return (
    <div>
      <PageHeader
        title="Live Cameras"
        subtitle="Live previews + uploaded footage · every camera analysed at 5 fps"
        actions={
          isAdmin ? (
            <div className="flex gap-2">
              <button className={btnSecondary} onClick={() => setUploadOpen(true)}>
                <Film className="h-4 w-4" /> Upload footage
              </button>
              <button
                className={btnPrimary}
                onClick={() => {
                  setEditing(null);
                  setModalOpen(true);
                }}
              >
                <Plus className="h-4 w-4" /> Add camera
              </button>
            </div>
          ) : undefined
        }
      />

      {cameras && cameras.length === 0 ? (
        <EmptyState
          title="No cameras yet"
          message="Admins can add real RTSP streams or simulated scenes (sim://loading_dock etc.) for a hardware-free demo."
          icon={<Camera className="h-8 w-8" />}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {cameras?.map((c) => (
            <CameraCard
              key={c.id}
              camera={c}
              isAdmin={isAdmin}
              onEdit={() => {
                setEditing(c);
                setModalOpen(true);
              }}
            />
          ))}
        </div>
      )}

      <CameraFormModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        camera={editing}
      />
      <UploadFootageModal
        open={uploadOpen}
        onClose={() => {
          setUploadOpen(false);
        }}
      />
    </div>
  );
}
