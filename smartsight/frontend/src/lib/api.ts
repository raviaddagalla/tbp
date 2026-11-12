"use client";

import axios from "axios";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

/** Absolute URL for <img>/<video> sources served by the backend. */
export function apiUrl(path: string | null | undefined): string {
  if (!path) return "";
  return `${API_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export const api = axios.create({
  baseURL: `${API_URL}/api`,
  timeout: 120_000,
});

export function errorMessage(err: unknown, fallback = "Something went wrong"): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: string })?.detail;
    if (detail) return detail;
    if (err.code === "ECONNABORTED") return "The request timed out";
    if (!err.response) return "Cannot reach the SmartSight backend. Is it running on port 8000?";
    return `${err.response.status} ${err.response.statusText || fallback}`;
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
