"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Clock3, LocateFixed } from "lucide-react";

import { apiUrl } from "@/lib/api";
import { formatClock } from "@/lib/format";

/**
 * Video playback for uploaded recordings.
 *
 * `seekSeconds` is the footage position of the matched frame. The backend
 * serves the file with HTTP Range support, so we set currentTime as soon as
 * metadata is available (and again on canplay, since some browsers reset it).
 */
export function VideoPlayer({
  src,
  seekSeconds = 0,
  title,
  className = "",
}: {
  src: string;
  seekSeconds?: number;
  title?: string;
  className?: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState("");
  const [jumped, setJumped] = useState(false);

  const jump = useCallback(() => {
    const video = ref.current;
    if (!video || !seekSeconds) return;
    try {
      video.currentTime = Math.max(0, seekSeconds);
      setJumped(true);
      setError("");
    } catch {
      setError("Could not seek inside this video");
    }
  }, [seekSeconds]);

  useEffect(() => {
    setError("");
    setJumped(false);
  }, [src, seekSeconds]);

  return (
    <div className={`overflow-hidden rounded-2xl bg-ink ${className}`}>
      <video
        ref={ref}
        src={apiUrl(src.startsWith("/api/") ? src : `/api${src.startsWith("/") ? "" : "/"}${src}`)}
        controls
        playsInline
        preload="metadata"
        className="max-h-[58vh] w-full bg-ink"
        onLoadedMetadata={jump}
        onCanPlay={() => {
          // Only auto-seek once; later plays must not snap back.
          if (!jumped) jump();
        }}
        onError={() => setError("This video could not be played. The file may have been deleted.")}
      />
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 px-3 py-2">
        <p className="flex min-w-0 items-center gap-1.5 truncate text-[11px] text-white/70">
          <Clock3 className="h-3.5 w-3.5 shrink-0" />
          {title || "Recording playback"}
          {seekSeconds > 0 && <span className="ml-1 font-mono text-white">· match at {formatClock(seekSeconds)}</span>}
        </p>
        <div className="flex items-center gap-2">
          {error && (
            <span className="flex items-center gap-1 text-[11px] text-rose-300">
              <AlertCircle className="h-3.5 w-3.5" /> {error}
            </span>
          )}
          {seekSeconds > 0 && (
            <button
              onClick={jump}
              className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-2 py-1 text-[11px] font-semibold text-white transition hover:bg-white/20"
            >
              <LocateFixed className="h-3.5 w-3.5" /> Jump to match
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
