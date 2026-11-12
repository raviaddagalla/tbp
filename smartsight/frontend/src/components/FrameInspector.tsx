"use client";

import React from "react";
import { Clock3, ScanEye, Video } from "lucide-react";

import { VideoPlayer } from "@/components/VideoPlayer";
import { Badge, Skeleton } from "@/components/ui";
import { apiUrl } from "@/lib/api";
import { formatClock, formatDateTime, titleCase } from "@/lib/format";
import type { FrameDetail } from "@/types";

/** Frame image with YOLO boxes plus the detections and playback for that moment. */
export function FrameInspector({
  detail,
  loading,
  recordingName,
}: {
  detail?: FrameDetail;
  loading?: boolean;
  recordingName?: string;
}) {
  if (loading || !detail) {
    return (
      <div className="space-y-3">
        <Skeleton className="aspect-video w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  const width = detail.width || 16;
  const height = detail.height || 9;

  return (
    <div className="space-y-3">
      <div className="relative overflow-hidden rounded-xl bg-ink" style={{ aspectRatio: `${width} / ${height}` }}>
        <img src={apiUrl(detail.thumbnail_url)} alt="Captured frame" className="absolute inset-0 h-full w-full object-contain" />
        {detail.detections.map((detection, index) => {
          const [x1, y1, x2, y2] = detection.bbox;
          return (
            <div
              key={`${detection.track_id}-${index}`}
              className="absolute rounded-[3px] border-2 border-primary/80"
              style={{
                left: `${x1 * 100}%`,
                top: `${y1 * 100}%`,
                width: `${Math.max(0.5, (x2 - x1) * 100)}%`,
                height: `${Math.max(0.5, (y2 - y1) * 100)}%`,
              }}
            >
              <span className="absolute -top-4 left-0 whitespace-nowrap rounded-sm bg-primary px-1 py-0.5 font-mono text-[8px] font-bold text-white">
                {titleCase(detection.object_class)}
                {detection.track_id ? ` #${detection.track_id}` : ""}
              </span>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Badge tone={detail.source_type === "live" ? "danger" : "primary"}>
          {detail.source_type === "live" ? "Live camera" : recordingName || "Recording"}
        </Badge>
        <Badge tone="neutral">
          <Clock3 className="mr-1 h-3 w-3" /> {formatDateTime(detail.captured_at)}
        </Badge>
        {detail.source_type === "upload" && <Badge tone="neutral">at {formatClock(detail.timestamp_seconds)}</Badge>}
        <Badge tone="neutral">frame #{detail.frame_number}</Badge>
        <Badge tone="success">{detail.objects_count} objects</Badge>
      </div>

      {detail.detections.length === 0 ? (
        <p className="flex items-center gap-1.5 rounded-xl bg-surface-low px-3 py-2 text-[11px] text-ink-muted">
          <ScanEye className="h-3.5 w-3.5" /> No objects were detected in this frame.
        </p>
      ) : (
        <ul className="grid gap-1.5 sm:grid-cols-2">
          {detail.detections.map((detection, index) => (
            <li key={index} className="flex items-center gap-2 rounded-xl border border-line px-2 py-1.5">
              {detection.thumbnail ? (
                <img src={apiUrl(`/api/media/thumb/${detection.thumbnail}`)} alt="" className="h-9 w-9 rounded-lg object-cover" />
              ) : (
                <span className="h-9 w-9 rounded-lg bg-surface-container" />
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate text-[11px] font-semibold text-ink">
                  {titleCase(detection.object_class)}
                  {detection.track_id ? ` #${detection.track_id}` : ""}
                </p>
                <p className="font-mono text-[9px] text-ink-muted">
                  {Math.round(detection.confidence * 100)}%{detection.colour ? ` · ${detection.colour}` : ""}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}

      {detail.source_type === "upload" && detail.recording_id ? (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wide text-ink-muted">
            <Video className="h-3 w-3" /> Original footage · seeking to {formatClock(detail.timestamp_seconds)}
          </p>
          <VideoPlayer
            src={`/recordings/${detail.recording_id}/playback`}
            seekSeconds={detail.timestamp_seconds}
            title={recordingName}
          />
        </div>
      ) : (
        <p className="rounded-xl bg-surface-low px-3 py-2 text-[11px] leading-relaxed text-ink-soft">
          Live frames are stored as timestamped snapshots, so this image is the full evidence for the moment.
        </p>
      )}
    </div>
  );
}
