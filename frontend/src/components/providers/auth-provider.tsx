"use client";

import { onAuthStateChanged, type User } from "firebase/auth";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import api from "@/lib/api";
import { auth } from "@/lib/firebase";

type UserProfile = {
  uid?: string;
  display_name?: string;
  email?: string;
  role?: string;
  default_branch_id?: string;
  created_at?: string;
  profile_exists?: boolean;
};

type AuthContextValue = {
  user: User | null;
  profile: UserProfile | null;
  displayName: string;
  loading: boolean;
};

const AUTH_STATE_TIMEOUT_MS = 12000;
const PROFILE_TIMEOUT_MS = 15000;

const AuthContext = createContext<AuthContextValue>({
  user: null,
  profile: null,
  displayName: "Authenticated User",
  loading: true
});

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const timeoutPromise = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(message)), timeoutMs);
  });

  return Promise.race([promise, timeoutPromise]).finally(() => {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
  });
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;
    let authStateResolved = false;

    const authStateTimeout = setTimeout(() => {
      if (!isMounted || authStateResolved) {
        return;
      }

      console.warn("Timed out while observing authentication state.");
      setUser(null);
      setProfile(null);
      setLoading(false);
    }, AUTH_STATE_TIMEOUT_MS);

    function resolveAuthState() {
      authStateResolved = true;
      clearTimeout(authStateTimeout);
    }

    const unsubscribe = onAuthStateChanged(auth, (nextUser) => {
      if (!isMounted) {
        return;
      }

      resolveAuthState();
      setUser(nextUser);

      if (!nextUser) {
        setProfile(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      void (async () => {
        try {
          const response = await withTimeout(
            api.get<UserProfile>("/api/v1/auth/me"),
            PROFILE_TIMEOUT_MS,
            "Timed out while loading authenticated user profile."
          );
          if (!isMounted) {
            return;
          }

          setProfile(response.data);
        } catch (error) {
          console.warn("Failed to load authenticated user profile.", error);
          if (isMounted) {
            setProfile(null);
          }
        } finally {
          if (isMounted) {
            setLoading(false);
          }
        }
      })();
    }, (authError) => {
      console.warn("Failed to observe authentication state.", authError);
      if (!isMounted) {
        return;
      }

      resolveAuthState();
      setUser(null);
      setProfile(null);
      setLoading(false);
    });

    return () => {
      isMounted = false;
      clearTimeout(authStateTimeout);
      unsubscribe();
    };
  }, []);

  const displayName =
    profile?.display_name?.trim() || user?.displayName || user?.email || "Authenticated User";

  const value = useMemo(
    () => ({
      user,
      profile,
      displayName,
      loading
    }),
    [displayName, loading, profile, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
