"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from "react";

import { useAuth } from "@/components/providers/auth-provider";
import api from "@/lib/api";
import type { Branch, BranchListResponse } from "@/types/branch";

type BranchContextValue = {
  branches: Branch[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
};

type CachedBranchesPayload = {
  branches: Branch[];
  expiresAt: number;
};

const BRANCH_CACHE_STORAGE_KEY = "branches_cache_v1";
const BRANCH_CACHE_TTL_MS = 10 * 60 * 1000;

const BranchContext = createContext<BranchContextValue>({
  branches: [],
  loading: false,
  error: null,
  refresh: () => undefined
});

function getErrorMessage(error: unknown): string {
  if (
    typeof error === "object" &&
    error &&
    "response" in error &&
    typeof (error as { response?: { data?: { detail?: unknown } } }).response === "object"
  ) {
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }

  return "Unable to load stores. Please try again.";
}

function readBranchCache(): CachedBranchesPayload | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(BRANCH_CACHE_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as CachedBranchesPayload;
    if (!Array.isArray(parsed.branches) || typeof parsed.expiresAt !== "number") {
      return null;
    }

    return parsed;
  } catch {
    return null;
  }
}

function writeBranchCache(branches: Branch[]): void {
  if (typeof window === "undefined") {
    return;
  }

  const payload: CachedBranchesPayload = {
    branches,
    expiresAt: Date.now() + BRANCH_CACHE_TTL_MS
  };
  window.localStorage.setItem(BRANCH_CACHE_STORAGE_KEY, JSON.stringify(payload));
}

function isCacheFresh(cache: CachedBranchesPayload | null): boolean {
  return !!cache && cache.expiresAt > Date.now();
}

export function BranchProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    if (authLoading) {
      return;
    }

    if (!user) {
      setBranches([]);
      setLoading(false);
      setError(null);
      return;
    }

    let isMounted = true;
    const forceRefresh = refreshNonce > 0;
    const cached = readBranchCache();

    if (!forceRefresh && cached) {
      setBranches(cached.branches);
      setLoading(false);
      setError(null);
      if (isCacheFresh(cached)) {
        return () => {
          isMounted = false;
        };
      }
    } else {
      setLoading(true);
    }

    async function loadBranches() {
      setLoading(true);
      setError(null);

      try {
        const response = await api.get<BranchListResponse>("/api/v1/branches");
        if (!isMounted) {
          return;
        }

        const branchList = response.data.branches || [];
        setBranches(branchList);
        writeBranchCache(branchList);
      } catch (fetchError) {
        if (!isMounted) {
          return;
        }

        setError(getErrorMessage(fetchError));
        if (!cached) {
          setBranches([]);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    void loadBranches();
    return () => {
      isMounted = false;
    };
  }, [authLoading, refreshNonce, user]);

  const value = useMemo(
    () => ({
      branches,
      loading,
      error,
      refresh: () => setRefreshNonce((current) => current + 1)
    }),
    [branches, error, loading]
  );

  return <BranchContext.Provider value={value}>{children}</BranchContext.Provider>;
}

export function useBranches(): BranchContextValue {
  return useContext(BranchContext);
}
