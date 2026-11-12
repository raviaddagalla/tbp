"use client";

import React, { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, RefreshCw, Search, Trash2, Upload } from "lucide-react";

import { EmptyState, ErrorState, PageHeader, ScoreBar, Spinner, StatusBadge, btnDanger, btnPrimary, inputCls } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth, hasRole } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import type { Document, DocumentSearchHit } from "@/types";

export default function DocumentsPage() {
  const { user } = useAuth();
  const isAdmin = hasRole(user, ["admin"]);
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [docQuery, setDocQuery] = useState("");
  const [docHits, setDocHits] = useState<DocumentSearchHit[] | null>(null);
  const [docSearching, setDocSearching] = useState(false);

  const { data: docs, isLoading, error, refetch } = useQuery({
    queryKey: ["documents"],
    queryFn: async () => (await api.get<Document[]>("/documents")).data,
    refetchInterval: 5000,
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      await api.post("/documents", fd);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });

  const uploadFile = async (file: File | undefined) => {
    if (!file) return;
    setUploadError(null);
    setUploading(true);
    try {
      await uploadMutation.mutateAsync(file);
    } catch (err) {
      setUploadError(errorMessage(err, "Upload failed"));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async (d: Document) => {
    if (!window.confirm(`Delete "${d.filename}" and remove its searchable chunks?`)) return;
    await api.delete(`/documents/${d.id}`);
    await qc.invalidateQueries({ queryKey: ["documents"] });
  };

  const retry = async (d: Document) => {
    await api.post(`/documents/${d.id}/retry`);
    await qc.invalidateQueries({ queryKey: ["documents"] });
  };

  const searchDocs = async () => {
    if (!docQuery.trim()) return;
    setDocSearching(true);
    try {
      const res = await api.post<DocumentSearchHit[]>("/search/documents", { query: docQuery.trim(), top_k: 10 });
      setDocHits(res.data);
    } catch (err) {
      setUploadError(errorMessage(err, "Search failed"));
    } finally {
      setDocSearching(false);
    }
  };

  if (isLoading) return <Spinner label="Loading documents…" />;
  if (error) return <ErrorState message="Could not load documents" onRetry={() => refetch()} />;

  return (
    <div>
      <PageHeader
        title="Document Library"
        subtitle="SOPs, safety guidelines and maintenance logs — parsed, chunked and embedded into the same vector space as video"
        actions={
          isAdmin ? (
            <button className={btnPrimary} onClick={() => fileRef.current?.click()} disabled={uploading}>
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {uploading ? "Uploading…" : "Upload document"}
            </button>
          ) : undefined
        }
      />
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.bmp,.tiff,.txt,.md"
        className="hidden"
        onChange={(e) => uploadFile(e.target.files?.[0])}
      />

      {uploadError && <div className="mb-4"><ErrorState message={uploadError} /></div>}

      <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex gap-2">
          <input
            className={inputCls}
            placeholder="Search inside documents… e.g. lockout tagout procedure"
            value={docQuery}
            onChange={(e) => setDocQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && searchDocs()}
          />
          <button className={btnPrimary + " shrink-0"} onClick={searchDocs} disabled={docSearching || !docQuery.trim()}>
            {docSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Search
          </button>
        </div>
        {docHits && (
          <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
            {docHits.length === 0 ? (
              <p className="text-sm text-slate-400">No matching sections found in the document library.</p>
            ) : (
              docHits.map((h) => (
                <div key={h.id} className="rounded-lg bg-blue-50 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-blue-900">
                      {h.filename} <span className="font-normal text-blue-600">· page {h.page} · {h.section}</span>
                    </p>
                    <ScoreBar score={h.score} />
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-blue-800">{h.chunk_text}</p>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {docs && docs.length === 0 ? (
        <EmptyState
          title="No documents yet"
          message="Upload SOPs, manuals, safety guidelines or maintenance logs (PDF, DOCX, images). Scanned files are OCR'd automatically."
          icon={<FileText className="h-8 w-8" />}
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase text-slate-500">
                <th className="px-4 py-3 font-medium">Document</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Pages / Chunks</th>
                <th className="px-4 py-3 font-medium">Uploaded</th>
                {isAdmin && <th className="px-4 py-3 font-medium text-right">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {docs?.map((d) => (
                <tr key={d.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-800">{d.filename}</p>
                    {d.ocr_used && <p className="text-xs text-slate-400">OCR applied</p>}
                  </td>
                  <td className="px-4 py-3 uppercase text-slate-500">{d.doc_type}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={d.status} />
                    {d.status === "failed" && <p className="mt-1 max-w-[280px] text-xs text-red-500">{d.error}</p>}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {d.pages} / {d.chunk_count}
                  </td>
                  <td className="px-4 py-3 text-slate-500">{formatDateTime(d.created_at)}</td>
                  {isAdmin && (
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        {d.status === "failed" && (
                          <button className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100" onClick={() => retry(d)} title="Retry">
                            <RefreshCw className="h-4 w-4" />
                          </button>
                        )}
                        <button className="rounded-lg p-1.5 text-red-500 hover:bg-red-50" onClick={() => remove(d)} title="Delete">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
