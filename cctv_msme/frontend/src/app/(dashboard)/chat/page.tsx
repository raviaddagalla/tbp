"use client";

import React, { useEffect, useRef, useState } from "react";
import { Bot, Loader2, MessageSquare, Play, Send } from "lucide-react";

import { EmptyState, ErrorState, ScoreBar, btnPrimary, inputCls } from "@/components/ui";
import { PlaybackModal } from "@/components/VideoPlayer";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ChatMessage, ChatResponse, Citation, VideoEvidence } from "@/types";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<VideoEvidence | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const res = await api.post<ChatResponse>("/chat", {
        message: text,
        history: messages.slice(-6),
      });
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.data.answer,
          citations: res.data.citations,
          video_evidence: res.data.video_evidence,
          intent: res.data.intent,
        },
      ]);
    } catch (err) {
      setError(errorMessage(err, "Assistant unavailable"));
    } finally {
      setBusy(false);
    }
  };

  const suggested = [
    "What is the lockout tagout procedure?",
    "Show me the forklift near the loading dock",
    "क्या सुरक्षा नियम हिंदी में बताओ",
  ];

  return (
    <div className="mx-auto flex h-[calc(100vh-7rem)] max-w-4xl flex-col">
      <div className="mb-4 flex items-center gap-2">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Factory Assistant</h1>
          <p className="text-sm text-slate-500">Answers from your documents and live indexed video — with citations and evidence clips</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        {messages.length === 0 && !busy && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 text-white shadow-lg">
              <Bot className="h-7 w-7" />
            </div>
            <h2 className="text-lg font-semibold text-slate-800">Ask anything about your factory</h2>
            <p className="mt-1 max-w-md text-sm text-slate-500">
              I search SOPs, safety documents and every indexed camera frame. I can also answer in Hindi.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {suggested.map((s) => (
                <button key={s} className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs text-blue-700 hover:bg-blue-100" onClick={() => setInput(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`mb-4 flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${m.role === "user" ? "rounded-br-md bg-blue-600 text-white" : "rounded-bl-md bg-slate-100 text-slate-800"}`}>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{m.content}</p>

              {m.video_evidence && m.video_evidence.length > 0 && (
                <div className="mt-3 space-y-2 border-t border-slate-300/40 pt-3">
                  {m.video_evidence.map((v) => (
                    <button key={v.clip_url} className="flex w-full items-center gap-2 rounded-lg bg-white/80 px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-white" onClick={() => setPlaying(v)}>
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white">
                        <Play className="h-3 w-3" />
                      </span>
                      <span className="truncate">
                        <span className="font-medium">{v.camera_name}</span> · {formatDateTime(v.timestamp)} · {v.zone}
                      </span>
                    </button>
                  ))}
                </div>
              )}

              {m.citations && m.citations.length > 0 && (
                <div className="mt-3 rounded-lg bg-white/70 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Sources</p>
                  <div className="mt-1 space-y-1">
                    {m.citations.map((c: Citation, j: number) => (
                      <p key={j} className="text-xs text-slate-500">
                        {j + 1}. {c.filename} — p{c.page}, {c.section}
                        <span className="ml-1 inline-block align-middle"><ScoreBar score={c.score} /></span>
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="mb-4 flex justify-start">
            <div className="flex items-center gap-2 rounded-2xl rounded-bl-md bg-slate-100 px-4 py-3 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Thinking…
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && (
        <div className="mt-3">
          <ErrorState message={error} />
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <input
          className={inputCls + " !py-3"}
          placeholder="Ask in English or Hindi…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          disabled={busy}
        />
        <button className={btnPrimary + " shrink-0 !px-5"} onClick={send} disabled={busy || !input.trim()}>
          <Send className="h-4 w-4" />
        </button>
      </div>

      {playing && (
        <PlaybackModal
          src={playing.clip_url}
          offsetSeconds={playing.clip_offset_seconds}
          title={`${playing.camera_name} · ${formatDateTime(playing.timestamp)} · ${playing.zone}`}
          onClose={() => setPlaying(null)}
        />
      )}
    </div>
  );
}
