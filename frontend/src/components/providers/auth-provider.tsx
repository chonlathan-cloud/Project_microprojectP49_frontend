"use client";

import { onAuthStateChanged, type User } from "firebase/auth";
import { doc, getDoc } from "firebase/firestore";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { auth, db } from "@/lib/firebase";

type UserProfile = {
  display_name?: string;
  email?: string;
  role?: string;
  default_branch_id?: string;
  created_at?: string;
};

type AuthContextValue = {
  user: User | null;
  profile: UserProfile | null;
  displayName: string;
  loading: boolean;
};

const AuthContext = createContext<AuthContextValue>({
  user: null,
  profile: null,
  displayName: "Authenticated User",
  loading: true
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    const unsubscribe = onAuthStateChanged(auth, (nextUser) => {
      if (!isMounted) {
        return;
      }

      setUser(nextUser);

      if (!nextUser) {
        setProfile(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      void (async () => {
        try {
          const profileDoc = await getDoc(doc(db, "users", nextUser.uid));
          if (!isMounted) {
            return;
          }

          if (profileDoc.exists()) {
            setProfile(profileDoc.data() as UserProfile);
          } else {
            setProfile(null);
          }
        } catch {
          if (isMounted) {
            setProfile(null);
          }
        } finally {
          if (isMounted) {
            setLoading(false);
          }
        }
      })();
    });

    return () => {
      isMounted = false;
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
