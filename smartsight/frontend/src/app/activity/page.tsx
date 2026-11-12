"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, ChevronRight, Filter, PauseCircle, PlayCircle, ScanEye } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { FrameInspector } from "@/components/FrameInspector";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Modal,
  PageHeader,
  ScoreBar,
  Segmented,
  Skeleton,
  btnSecondary,
} from "@/components/ui";
import { api, apiUrl, errorMessage } from "@/lib/api";
import { compactNumber, formatClock, formatDateTime, timeAgo, titleCase } from "@/lib/format";
import type { DetectionItem, FrameDetail, ObjectClassCount } from "@/types";

interface ActivityResponse {
  items: DetectionItem[];
  classes: ObjectClassCount[];
}

export default function ActivityPage() {
  const [objectClass, setObjectClass] = useState("");
  const [source, setSource] = useState<"all" | "live" | "upload">("all");
  const [limit, setLimit] = useState(40);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedName, setSelectedName] = useState("");

  // Deep link from the overview / search inspector: /activity?frame_id=123
  useEffect(() => {
    const frame = Number(new URLSearchParams(window.location.search).get("frame_id"));
    if (Number.isFinite(frame) && frame > 0) setSelectedId(frame);
  }, []);

  const feed = useQuery({
    queryKey: ["activity", limit, objectClass, source],
    queryFn: async () => {
      const response = await api.get<ActivityResponse>("/activity", {
        params: {
          limit,
          object_class: objectClass || undefined,
          source_type: source === "all" ? undefined : source,
        },
      });
      return response.data;
    },
    refetchInterval: autoRefresh ? 6_000 : false,
  });

  const detail = useQuery({
    queryKey: ["frame-detail", selectedId],
    queryFn: async () => (await api.get<FrameDetail>(`/frames/${selectedId}`)).data,
    enabled: Boolean(selectedId),
  });

  const items = feed.data?.items ?? [];
  const classes = feed.data?.classes ?? [];

  const grouped = useMemo(() => {
    const map = new Map<string, DetectionItem[]>();
    for (const item of items) {
      const date = new Date(item.captured_at);
      const key = Number.isNaN(date.getTime())
        ? "Unknown date"
        : date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
      const bucket = map.get(key);
      if (bucket) bucket.push(item);
      else map.set(key, [item]);
    }
    return Array.from(map.entries());
  }, [items]);

  const liveCount = items.filter((item) => item.source_type === "live").length;
  const uploadCount = items.length - liveCount;

  return (
    <AppShell>
      <PageHeader
        eyebrow="Chronological feed"
        title="Detection activity"
        subtitle="Every YOLO detection with its tracking ID, confidence, timestamp and a link back to the exact frame."
        actions={
          <button onClick={() => setAutoRefresh((value) => !value)} className={btnSecondary}>
            {autoRefresh ? <PauseCircle className="h-4 w-4" /> : <PlayCircle className="h-4 w-4" />}
            {autoRefresh ? "Pause feed" : "Resume feed"}
          </button>
        }
      />

      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-ink-muted">
            <Filter className="h-3.5 w-3.5" /> Filters
          </span>
          <Segmented
            value={source}
            onChange={(value) => setSource(value as "all" | "live" | "upload")}
            options={[
              { value: "all", label: `All (${items.length})` },
              { value: "live", label: `Live (${liveCount})` },
              { value: "upload", label: `Uploads (${uploadCount})` },
            ]}
          />
          <span className="mx-1 hidden h-4 w-px bg-line sm:block" />
          <button
            onClick={() => setObjectClass("")}
            className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition ${
              objectClass === "" ? "bg-ink text-white" : "bg-surface-container text-ink-soft hover:bg-surface-high"
            }`}
          >
            Every class
          </button>
          {classes.map((item) => (
            <button
              key={item.object_class}
              onClick={() => setObjectClass(item.object_class === objectClass ? "" : item.object_class)}
              className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize transition ${
                objectClass === item.object_class
                  ? "bg-primary text-white"
                  : "bg-primary-soft/60 text-primary hover:bg-primary-soft"
              }`}
            >
              {titleCase(item.object_class)} · {compactNumber(item.count)}
            </button>
          ))}
        </div>
      </Card>

      <div className="mt-4">
        {feed.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3, 4].map((key) => (
              <Skeleton key={key} className="h-[74px]" />
            ))}
          </div>
        ) : feed.isError ? (
          <ErrorState message={errorMessage(feed.error, "Could not load the activity feed")} onRetry={() => feed.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No detections match"
            message={
              objectClass || source !== "all"
                ? "Clear the filters to see everything, or start the camera / upload a video to generate detections."
                : "Start monitoring the camera or upload a recording. Objects detected by YOLO will stream into this feed."
            }
            icon={<Activity className="h-7 w-7" />}
          />
        ) : (
          <div className="space-y-5">
            {grouped.map(([day, rows]) => (
              <section key={day}>
                <div className="mb-2 flex items-center gap-2">
                  <h2 className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-ink-muted">{day}</h2>
                  <span className="h-px flex-1 bg-line" />
                  <span className="font-mono text-[10px] text-ink-muted">{rows.length} detections</span>
                </div>
                <ul className="space-y-1.5">
                  {rows.map((item) => (
                    <li key={item.id}>
                      <button
                        onClick={() => {
                          setSelectedId(item.frame_id);
                          setSelectedName(item.source_type === "live" ? "" : item.recording_name);
                        }}
                        className="flex w-full items-center gap-3 rounded-xl border border-line bg-white px-2.5 py-2 text-left transition hover:border-primary/40 hover:shadow-card"
                      >
                        <div className="relative h-12 w-16 shrink-0 overflow-hidden rounded-lg bg-surface-container">
                          {item.thumbnail_url ? (
                            <img src={apiUrl(item.thumbnail_url)} alt="" className="h-full w-full object-cover" loading="lazy" />
                          ) : (
                            <div className="flex h-full items-center justify-center text-ink-muted">
                              <ScanEye className="h-4 w-4" />
                            </div>
                          )}
                        </div>

                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-[12px] font-bold capitalize text-ink">{titleCase(item.object_class)}</span>
                            {item.track_id > 0 && (
                              <span className="rounded bg-primary-soft px-1.5 py-0.5 font-mono text-[9px] font-bold text-primary">
                                #{item.track_id}
                              </span>
                            )}
                            {item.colour && <Badge tone="neutral">{item.colour}</Badge>}
                          </div>
                          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] text-ink-muted">
                            <span className={item.source_type === "live" ? "text-primary" : ""}>
                              {item.source_type === "live" ? "ESP32 LIVE" : item.recording_name}
                            </span>
                            {item.source_type === "upload" && <span>@{formatClock(item.timestamp_seconds)}</span>}
                            <span>{formatDateTime(item.captured_at)}</span>
                            <span>· {timeAgo(item.captured_at)}</span>
                          </div>
                        </div>

                        <div className="hidden w-28 shrink-0 sm:block">
                          <ScoreBar score={item.confidence} />
                        </div>
                        <span className="hidden w-10 shrink-0 text-right font-mono text-[11px] font-semibold text-ink sm:block">
                          {Math.round(item.confidence * 100)}%
                        </span>
                        <ChevronRight className="h-4 w-4 shrink-0 text-ink-muted" />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}

            <div className="flex items-center justify-center gap-2">
              {items.length >= limit && limit < 200 && (
                <button onClick={() => setLimit((value) => Math.min(200, value + 40))} className={btnSecondary}>
                  Load {Math.min(40, 200 - limit)} more detections
                </button>
              )}
              <span className="font-mono text-[10px] text-ink-muted">
                showing {items.length} · auto-refresh {autoRefresh ? "every 6s" : "paused"}
              </span>
            </div>
          </div>
        )}
      </div>

      <Modal
        open={Boolean(selectedId)}
        onClose={() => setSelectedId(null)}
        title="Detection frame"
        subtitle={detail.data ? formatDateTime(detail.data.captured_at) : "Loading frame…"}
        wide
      >
        <FrameInspector detail={detail.data} loading={detail.isLoading} recordingName={selectedName} />
      </Modal>
    </AppShell>
  );
}
