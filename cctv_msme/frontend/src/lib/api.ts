"use client";

import axios from "axios";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_URL = API_URL.replace(/^http/, "ws") + "/api/ws/events";

const USER_KEY = "fi_user";

export function setUser(user: unknown) {
  if (typeof window === "undefined") return;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(USER_KEY);
  mediaTokenCache.clear();
}

export function getStoredUser<T>() {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

/**
 * Media URLs for <img>/<video> tags, which cannot send cookies or
 * Authorization headers cross-origin. Each URL gets a SHORT-LIVED (5 min),
 * single-resource token minted from the server — never the session token.
 */
const mediaTokenCache = new Map<string, { token: string; at: number }>();
const MEDIA_TOKEN_CACHE_MS = 4 * 60 * 1000;

export async function authedUrl(path: string): Promise<string> {
  const cached = mediaTokenCache.get(path);
  if (cached && Date.now() - cached.at < MEDIA_TOKEN_CACHE_MS) {
    return `${API_URL}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(cached.token)}`;
  }
  try {
    const res = await api.post<{ token: string }>("/auth/media-token", { path });
    mediaTokenCache.set(path, { token: res.data.token, at: Date.now() });
    return `${API_URL}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(res.data.token)}`;
  } catch {
    // Unauthenticated or server unavailable: return the bare URL; the media
    // endpoint will 401/403 and the <img> falls back gracefully.
    return `${API_URL}${path}`;
  }
}

/** Download helper for export links that need auth (blob fetch + save). */
export async function downloadFile(path: string, filename: string) {
  const res = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const api = axios.create({
  baseURL: `${API_URL}/api`,
  withCredentials: true,
  timeout: 60000,
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
      clearSession();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  }
);

export function errorMessage(err: unknown, fallback = "Something went wrong"): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: string })?.detail;
    if (detail) return detail;
    if (err.code === "ECONNABORTED") return "Request timed out";
    if (!err.response) return "Cannot reach the server. Is the backend running?";
  }
  return fallback;
}
