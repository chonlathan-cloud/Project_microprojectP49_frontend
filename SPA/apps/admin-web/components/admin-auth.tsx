"use client";

import {
  getRedirectResult,
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signOut,
  type AuthError,
  type User
} from "firebase/auth";
import { useEffect, useState, type ReactNode } from "react";

import { getFirebaseAuth } from "@/lib/firebase";

type Props = { children: (user: User) => ReactNode };

function authErrorMessage(error: unknown): string {
  const code = (error as Partial<AuthError>)?.code;
  if (code === "auth/popup-blocked") {
    return "Google Sign-In popup was blocked. Allow popups for this site and try again.";
  }
  if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") {
    return "Google Sign-In was cancelled. Please try again.";
  }
  if (code === "auth/unauthorized-domain") {
    return "This Admin domain is not authorized in Firebase Authentication.";
  }
  return error instanceof Error ? error.message : "Google Sign-In failed";
}

export function AdminAuth({ children }: Props) {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let unsubscribe: () => void = () => {};
    let active = true;
    try {
      const auth = getFirebaseAuth();
      getRedirectResult(auth).catch((caught) => {
        if (active) setError(authErrorMessage(caught));
      });
      unsubscribe = onAuthStateChanged(auth, async (nextUser) => {
        if (!active) return;
        setUser(nextUser);
        setLoading(false);
        if (!nextUser) {
          setError("");
        }
      });
    } catch (caught) {
      queueMicrotask(() => {
        if (active) {
          setError(authErrorMessage(caught));
          setLoading(false);
        }
      });
    }
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  async function login() {
    try {
      setError("");
      const provider = new GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
      await signInWithPopup(getFirebaseAuth(), provider);
    } catch (caught) {
      setError(authErrorMessage(caught));
    }
  }

  if (loading) return <div className="auth-gate">Checking Firebase Authentication…</div>;
  if (!user) return <main className="auth-gate"><h1>SPA 49 Admin</h1><p>{error || "Sign in with an invited Google account to continue."}</p><button className="primary-button" onClick={login}>Sign in with Google</button></main>;
  return <>{children(user)}<button className="auth-signout" onClick={() => signOut(getFirebaseAuth())}>Sign out</button></>;
}
