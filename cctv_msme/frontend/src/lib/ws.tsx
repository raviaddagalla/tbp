"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { WS_URL, api } from "@/lib/api";
import type { WsEvent } from "@/types";

interface WsContextValue {
  connected: boolean;
  events: WsEvent[];
  activity: { id: string; kind: string; message: string; created_at: string }[];
  cameraStatus: Record<number, { status: string; error?: string }>;
  liveAlerts: WsEvent[];
}

const WsContext = createContext<WsContextValue>({
  connected: false,
  events: [],
  activity: [],
  cameraStatus: {},
  liveAlerts: [],
});

let seq = 0;

export function WsProvider({ children }: { children: React.ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [activity, setActivity] = useState<WsContextValue["activity"]>([]);
  const [cameraStatus, setCameraStatus] = useState<Record<number, { status: string; error?: string }>>({});
  const [liveAlerts, setLiveAlerts] = useState<WsEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const connectRef = useRef<() => Promise<void>>(async () => {});

  const connect = useCallback(async () => {
    try {
      // The WS handshake cannot send the httpOnly cookie cross-origin, so it
      // authenticates with a short-lived media token scoped to /ws/events.
      const res = await api.post<{ token: string }>("/auth/media-token", { path: "/api/ws/events" });
      const ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(res.data.token)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 0;
      };
      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data as string) as WsEvent;
          if (data.type === "activity_history") {
            const items = (data.payload.items as { id?: number; kind: string; message: string; created_at: string }[]) || [];
            setActivity(
              items.map((it) => ({ id: String(it.id ?? seq++), kind: it.kind, message: it.message, created_at: it.created_at }))
            );
            return;
          }
          setEvents((prev) => [data, ...prev].slice(0, 100));
          if (data.type === "activity") {
            const p = data.payload as { kind: string; message: string; camera_id?: number | null };
            setActivity((prev) =>
              [{ id: String(seq++), kind: p.kind, message: p.message, created_at: new Date().toISOString() }, ...prev].slice(0, 60)
            );
          } else if (data.type === "camera_status") {
            const p = data.payload as { camera_id: number; status: string; error?: string };
            setCameraStatus((prev) => ({ ...prev, [p.camera_id]: { status: p.status, error: p.error } }));
          } else if (data.type === "alert") {
            setLiveAlerts((prev) => [data, ...prev].slice(0, 20));
          }
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        setTimeout(() => {
          retryRef.current += 1;
          if (retryRef.current < 8) void connectRef.current();
        }, 3000 * retryRef.current);
      };
      ws.onerror = () => ws.close();
    } catch {
      // Not authenticated — reconnect attempts will keep failing quietly.
    }
  }, []);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    void connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  const value = useMemo(
    () => ({ connected, events, activity, cameraStatus, liveAlerts }),
    [connected, events, activity, cameraStatus, liveAlerts]
  );

  return <WsContext.Provider value={value}>{children}</WsContext.Provider>;
}

export function useWs() {
  return useContext(WsContext);
}
