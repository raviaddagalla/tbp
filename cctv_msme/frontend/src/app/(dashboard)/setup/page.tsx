"use client";

import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera as CameraIcon, Check, KeyRound, Loader2, MapPin } from "lucide-react";
import { useRouter } from "next/navigation";

import { Field, PageHeader, btnPrimary, btnSecondary, inputCls } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Camera } from "@/types";

function StepCard({
  step,
  title,
  description,
  done,
  children,
}: {
  step: number;
  title: string;
  description: string;
  done: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`rounded-xl border bg-white p-5 shadow-sm ${done ? "border-emerald-200" : "border-slate-200"}`}>
      <div className="mb-1 flex items-center gap-3">
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${done ? "bg-emerald-100 text-emerald-700" : "bg-blue-600 text-white"}`}>
          {done ? <Check className="h-4 w-4" /> : step}
        </span>
        <div>
          <h2 className="font-semibold text-slate-900">{title}</h2>
          <p className="text-xs text-slate-500">{description}</p>
        </div>
      </div>
      <div className="mt-4">{done ? <p className="text-xs font-medium text-emerald-600">Done</p> : children}</div>
    </div>
  );
}

export default function SetupPage() {
  const { user, refresh } = useAuth();
  const qc = useQueryClient();
  const router = useRouter();
  const [pw, setPw] = useState("");
  const [cam, setCam] = useState({ name: "", rtsp_url: "", zone: "General" });
  const [error, setError] = useState<string | null>(null);

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: async () => (await api.get<Camera[]>("/cameras")).data,
  });

  const { data: floorplan } = useQuery({
    queryKey: ["floorplan"],
    queryFn: async () => (await api.get<{ id: number | null; name: string; pins: Record<string, unknown> }>("/floorplan")).data,
  });

  const pwMutation = useMutation({
    mutationFn: async () => {
      if (!user) throw new Error("Not signed in");
      await api.patch(`/users/${user.id}`, { password: pw });
    },
    onSuccess: () => {
      setPw("");
      setError(null);
      refresh();
    },
    onError: (err) => setError(errorMessage(err, "Could not change password")),
  });

  const camMutation = useMutation({
    mutationFn: async () => {
      await api.post("/cameras", { ...cam, name: cam.name || "Camera 1" });
    },
    onSuccess: () => {
      setCam({ name: "", rtsp_url: "", zone: "General" });
      setError(null);
      qc.invalidateQueries({ queryKey: ["cameras"] });
    },
    onError: (err) => setError(errorMessage(err, "Could not add camera")),
  });

  const camerasDone = (cameras?.length ?? 0) > 0;
  const floorplanDone = !!floorplan?.id;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Setup checklist"
        subtitle="First-run onboarding for a new site. Everything here is also available in the normal UI."
      />

      {error && (
        <div className="mb-4">
          <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
        </div>
      )}

      <div className="space-y-5">
        <StepCard
          step={1}
          title="Change the default admin password"
          description="The seeded admin account uses a known default password — set your own before going live."
          done={false}
        >
          <div className="flex gap-2">
            <input
              type="password"
              className={inputCls}
              placeholder="New password (min 8 chars)"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
            />
            <button className={btnPrimary + " shrink-0"} disabled={pwMutation.isPending || pw.length < 8} onClick={() => pwMutation.mutate()}>
              {pwMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
              Set password
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-400">You stay signed in; a fresh login will use the new password.</p>
        </StepCard>

        <StepCard
          step={2}
          title="Add your first camera"
          description="Connect an RTSP stream (or upload footage later from the Cameras page)."
          done={camerasDone}
        >
          <div className="space-y-3">
            <Field label="Camera name">
              <input className={inputCls} placeholder="e.g. Gate 1" value={cam.name} onChange={(e) => setCam({ ...cam, name: e.target.value })} />
            </Field>
            <Field label="RTSP URL">
              <input
                className={inputCls}
                placeholder="rtsp://user:pass@host:554/stream"
                value={cam.rtsp_url}
                onChange={(e) => setCam({ ...cam, rtsp_url: e.target.value })}
              />
            </Field>
            <Field label="Zone">
              <input className={inputCls} placeholder="e.g. Loading Dock" value={cam.zone} onChange={(e) => setCam({ ...cam, zone: e.target.value })} />
            </Field>
            <button className={btnPrimary} disabled={camMutation.isPending} onClick={() => camMutation.mutate()}>
              {camMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CameraIcon className="h-4 w-4" />}
              Add camera
            </button>
          </div>
        </StepCard>

        <StepCard
          step={3}
          title="Upload the site floor plan"
          description="Place camera pins and draw adjacency edges so cross-camera trails can be stitched."
          done={floorplanDone}
        >
          <button className={btnSecondary} onClick={() => router.push("/floorplan")}>
            <MapPin className="h-4 w-4" /> Open floor plan editor
          </button>
        </StepCard>

        {camerasDone && floorplanDone && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
            <p className="font-semibold">Setup complete</p>
            <p className="mt-1 text-xs">Cameras are ingesting and the site map is calibrated. Continue from the dashboard.</p>
          </div>
        )}
      </div>
    </div>
  );
}
