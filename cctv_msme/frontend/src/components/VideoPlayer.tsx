"use client";

import React, { useEffect, useRef, useState } from "react";
import { Play, X } from "lucide-react";

import { authedUrl } from "@/lib/api";

export function VideoPlayer({ src, offsetSeconds, title }: { src: string; offsetSeconds?: number; title?: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState(false);
  const [mediaSrc, setMediaSrc] = useState<string | undefined>(undefined);

  // Uploaded-footage cameras: the raw file is huge and unseekable in the
  // browser, so request a server-cut clip around the target moment
  // (5s before / 5s after the matched frame).
  const fileCam = src.match(/\/api\/streams\/file\/(\d+)/)?.[1];
  const fileOffset = fileCam && offsetSeconds ? Math.max(0, offsetSeconds - 5) : null;
  const resolvedSrc = fileOffset !== null ? `/api/streams/file/${fileCam}/clip?start=${fileOffset.toFixed(1)}&duration=10` : src;
  const seekTo = fileOffset !== null ? Math.min(5, offsetSeconds!) : offsetSeconds;

  useEffect(() => {
    let alive = true;
    authedUrl(resolvedSrc).then((u) => {
      if (alive) {
        setError(false);
        setMediaSrc(u);
      }
    });
    return () => {
      alive = false;
    };
  }, [resolvedSrc]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const trySeek = () => {
      if (seekTo && seekTo > 0.5) {
        v.currentTime = seekTo;
      }
      v.removeEventListener("loadedmetadata", trySeek);
    };
    v.addEventListener("loadedmetadata", trySeek);
    return () => v.removeEventListener("loadedmetadata", trySeek);
  }, [mediaSrc, seekTo]);

  return (
    <div className="overflow-hidden rounded-xl bg-slate-950">
      {error ? (
        <div className="flex h-56 items-center justify-center text-sm text-slate-400">
          Clip unavailable (segment may have been pruned or the camera has no clips yet)
        </div>
      ) : (
        mediaSrc && (
          <video
            ref={videoRef}
            src={mediaSrc}
            controls
            playsInline
            poster={undefined}
            className="max-h-[60vh] w-full bg-slate-950"
            onError={() => setError(true)}
          />
        )
      )}
      {title && <p className="px-3 py-2 text-xs text-slate-400">{title}</p>}
    </div>
  );
}

export function PlaybackModal({
  src,
  offsetSeconds,
  title,
  onClose,
}: {
  src: string;
  offsetSeconds?: number;
  title?: string;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center justify-between">
          <p className="flex items-center gap-2 text-sm font-medium text-white">
            <Play className="h-4 w-4 text-blue-400" /> {title || "Clip playback"}
          </p>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-300 hover:bg-white/10">
            <X className="h-5 w-5" />
          </button>
        </div>
        <VideoPlayer src={src} offsetSeconds={offsetSeconds} />
      </div>
    </div>
  );
}
