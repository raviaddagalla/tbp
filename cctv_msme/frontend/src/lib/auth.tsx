"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { api, clearSession, getStoredUser, setUser } from "@/lib/api";
import type { User } from "@/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  login: async () => {},
  logout: () => {},
  refresh: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(() => {
    if (typeof window === "undefined") return null;
    return getStoredUser<User>();
  });
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const refresh = useCallback(async () => {
    try {
      // Session lives in an httpOnly cookie; /auth/me tells us if it's valid.
      const res = await api.get<User>("/auth/me");
      setUser(res.data);
      setUserState(res.data);
    } catch {
      clearSession();
      setUserState(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    api
      .get<User>("/auth/me")
      .then((res) => {
        if (!alive) return;
        setUser(res.data);
        setUserState(res.data);
      })
      .catch(() => {
        if (!alive) return;
        clearSession();
        setUserState(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api.post<{ access_token: string; user: User }>("/auth/login", { username, password });
      setUser(res.data.user);
      setUserState(res.data.user);
      router.push("/");
    },
    [router]
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // cookie may already be gone; continue locally
    }
    clearSession();
    setUserState(null);
    router.push("/login");
  }, [router]);

  const value = useMemo(
    () => ({ user, loading, login, logout, refresh }),
    [user, loading, login, logout, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

export function hasRole(user: User | null, roles: string[]): boolean {
  return !!user && roles.includes(user.role);
}
