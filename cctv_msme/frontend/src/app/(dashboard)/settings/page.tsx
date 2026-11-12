"use client";

import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Trash2, UserPlus } from "lucide-react";

import { EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusBadge, btnDanger, btnPrimary, btnSecondary, inputCls } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth, hasRole } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import type { User } from "@/types";

const ROLE_OPTIONS = ["worker", "supervisor", "admin"] as const;

export default function SettingsPage() {
  const { user: me, refresh } = useAuth();
  const qc = useQueryClient();
  const isAdmin = hasRole(me, ["admin"]);
  const [modalOpen, setModalOpen] = useState(false);
  const [passwordModal, setPasswordModal] = useState(false);
  const [form, setForm] = useState({ username: "", password: "", role: "worker" as string, zone: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { data: users, isLoading, refetch } = useQuery({
    queryKey: ["users"],
    queryFn: async () => (await api.get<User[]>("/users")).data,
    enabled: isAdmin,
  });

  const createUser = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/users", form);
      setForm({ username: "", password: "", role: "worker", zone: "" });
      setModalOpen(false);
      await qc.invalidateQueries({ queryKey: ["users"] });
    } catch (err) {
      setError(errorMessage(err, "Could not create user"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (u: User) => {
    if (u.id === me?.id) return window.alert("You cannot delete your own account.");
    if (!window.confirm(`Delete user "${u.username}"?`)) return;
    await api.delete(`/users/${u.id}`);
    await qc.invalidateQueries({ queryKey: ["users"] });
  };

  const changePassword = async () => {
    setBusy(true);
    setError(null);
    try {
      const pw = (document.getElementById("new-password") as HTMLInputElement)?.value;
      if (!pw || pw.length < 8) throw new Error("Password must be at least 8 characters.");
      await api.post("/auth/change-password", { new_password: pw });
      setPasswordModal(false);
      await refresh();
      window.alert("Password updated.");
    } catch (err) {
      setError(errorMessage(err, "Could not change password"));
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) return <Spinner label="Loading users…" />;

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Settings"
        subtitle="Role-based access — workers see only their zone's cameras; supervisors get search, alerts and reports"
        actions={
          isAdmin ? (
            <button className={btnPrimary} onClick={() => setModalOpen(true)}>
              <UserPlus className="h-4 w-4" /> Add user
            </button>
          ) : undefined
        }
      />

      <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <p className="mb-1 text-sm font-semibold text-slate-800">My account</p>
        <p className="text-sm text-slate-500">
          {me?.username} · <span className="capitalize">{me?.role}</span>
          {me?.zone ? ` · zone: ${me.zone}` : ""}
        </p>
        <button className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" onClick={() => setPasswordModal(true)}>
          <KeyRound className="h-3.5 w-3.5" /> Change password
        </button>
      </div>

      {isAdmin && users && users.length === 0 && (
        <EmptyState title="No users" message="Add team members with role-based access." />
      )}

      {isAdmin && users && users.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase text-slate-500">
                <th className="px-4 py-3 font-medium">Username</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Zone</th>
                <th className="px-4 py-3 font-medium">Created</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-800">
                    {u.username}
                    {u.id === me?.id && <span className="ml-2 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] text-blue-700">you</span>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${u.role === "admin" ? "bg-purple-100 text-purple-700" : u.role === "supervisor" ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-600"}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{u.zone || "—"}</td>
                  <td className="px-4 py-3 text-slate-500">{formatDateTime(u.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button className="rounded-lg p-1.5 text-red-500 hover:bg-red-50 disabled:opacity-40" disabled={u.id === me?.id} onClick={() => remove(u)} title="Delete user">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Add user">
        <div className="space-y-4">
          <Field label="Username">
            <input className={inputCls} value={form.username} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} />
          </Field>
          <Field label="Password" hint="At least 8 characters">
            <input type="password" className={inputCls} value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
          </Field>
          <Field label="Role">
            <select className={inputCls} value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
              {ROLE_OPTIONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </Field>
          <Field label="Zone (workers only)" hint="Workers only see cameras in this zone">
            <input className={inputCls} value={form.zone} onChange={(e) => setForm((f) => ({ ...f, zone: e.target.value }))} placeholder="Loading Dock" />
          </Field>
          {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button className={btnSecondary} onClick={() => setModalOpen(false)}>Cancel</button>
            <button className={btnPrimary} onClick={createUser} disabled={busy || !form.username || form.password.length < 8}>
              Create user
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={passwordModal} onClose={() => setPasswordModal(false)} title="Change my password">
        <div className="space-y-4">
          <Field label="New password" hint="At least 8 characters">
            <input id="new-password" type="password" className={inputCls} />
          </Field>
          {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button className={btnSecondary} onClick={() => setPasswordModal(false)}>Cancel</button>
            <button className={btnPrimary} onClick={changePassword} disabled={busy}>Update password</button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
