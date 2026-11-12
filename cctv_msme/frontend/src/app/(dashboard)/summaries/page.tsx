"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Download, FileOutput, FileText, Loader2 } from "lucide-react";

import { EmptyState, ErrorState, Field, PageHeader, Spinner, btnPrimary, inputCls } from "@/components/ui";
import { api, downloadFile, errorMessage } from "@/lib/api";
import { useAuth, hasRole } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import type { Summary } from "@/types";

const HOUR_OPTIONS = [
  { hours: 8, label: "Shift (8h)" },
  { hours: 12, label: "Long shift (12h)" },
  { hours: 24, label: "Daily (24h)" },
  { hours: 72, label: "Last 3 days" },
  { hours: 168, label: "Weekly (7d)" },
];

export default function SummariesPage() {
  const { user } = useAuth();
  const isSupervisor = hasRole(user, ["supervisor", "admin"]);
  const [hours, setHours] = useState(8);
  const [title, setTitle] = useState("Shift summary");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: summaries, isLoading, error: loadError, refetch } = useQuery({
    queryKey: ["summaries"],
    queryFn: async () => (await api.get<Summary[]>("/summaries")).data,
  });

  const sorted = useMemo(() => (summaries ?? []).slice().sort((a, b) => b.id - a.id), [summaries]);

  const generate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await api.post<Summary>("/summaries", { hours, title });
      await refetch();
      document.getElementById(`summary-${res.data.id}`)?.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      setError(errorMessage(err, "Could not generate summary"));
    } finally {
      setGenerating(false);
    }
  };

  if (isLoading) return <Spinner label="Loading summaries…" />;
  if (loadError) return <EmptyState title="Could not load summaries" message={errorMessage(loadError)} />;

  return (
    <div>
      <PageHeader title="Shift Summaries" subtitle="AI-generated production reports combining video activity, documents and safety alerts" />

      <div className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <Field label="Reporting window">
          <select className={inputCls} value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {HOUR_OPTIONS.map((o) => (
              <option key={o.hours} value={o.hours}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Title">
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        {isSupervisor && (
          <button className={btnPrimary} onClick={generate} disabled={generating}>
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
            {generating ? "Generating…" : "Generate summary"}
          </button>
        )}
      </div>

      {error && <div className="mb-4"><p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p></div>}

      {sorted.length === 0 ? (
        <EmptyState
          title="No summaries yet"
          message="Summaries are generated from the window's activity feed, search queries and safety alerts."
          icon={<CalendarDays className="h-8 w-8" />}
        />
      ) : (
        <div className="space-y-4">
          {sorted.map((s) => (
            <div key={s.id} id={`summary-${s.id}`} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-4 py-3">
                <div>
                  <p className="font-semibold text-slate-900">{s.title}</p>
                  <p className="text-xs text-slate-500">
                    {formatDateTime(s.window_start)} → {formatDateTime(s.window_end)} · by {s.created_by}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void downloadFile(`/summaries/${s.id}/export?format=txt`, `summary_${s.id}.txt`)}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    <Download className="mr-1 inline h-3 w-3" /> TXT
                  </button>
                  <button
                    onClick={() => void downloadFile(`/summaries/${s.id}/export?format=html`, `summary_${s.id}.html`)}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    <FileOutput className="mr-1 inline h-3 w-3" /> HTML
                  </button>
                </div>
              </div>
              <div className="px-4 py-4">
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{s.content}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
