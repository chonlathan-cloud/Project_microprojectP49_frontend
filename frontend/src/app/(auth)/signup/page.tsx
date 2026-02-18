"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { createUserWithEmailAndPassword, updateProfile } from "firebase/auth";
import { doc, setDoc } from "firebase/firestore";
import { UserPlus } from "lucide-react";

import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { auth, db } from "@/lib/firebase";

const BRANCH_OPTIONS = [
  { id: "branch_coffee", label: "Coffee Shop" },
  { id: "branch_restaurant", label: "Restaurant" },
  { id: "branch_steak", label: "Steak House" }
];

function getSignupErrorMessage(code: string): string {
  if (code === "auth/email-already-in-use") {
    return "This email is already in use.";
  }
  if (code === "auth/invalid-email") {
    return "Invalid email format.";
  }
  if (code === "auth/weak-password") {
    return "Password is too weak. Please use at least 6 characters.";
  }
  if (code === "auth/operation-not-allowed") {
    return "Email/password sign-up is not enabled in Firebase Authentication.";
  }
  if (code === "profile-setup-failed") {
    return "Account created, but profile setup failed. You can still log in and continue.";
  }
  return "Sign up failed. Please try again.";
}

export default function SignupPage() {
  const router = useRouter();
  const { user, loading } = useAuth();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [defaultBranchId, setDefaultBranchId] = useState(BRANCH_OPTIONS[0]?.id ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) {
      router.replace("/dashboard/upload-receipt");
    }
  }, [loading, router, user]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    if (password !== confirmPassword) {
      setError("Password and confirm password do not match.");
      setSubmitting(false);
      return;
    }

    try {
      const credential = await createUserWithEmailAndPassword(auth, email.trim(), password);
      const normalizedDisplayName = displayName.trim();

      try {
        await updateProfile(credential.user, { displayName: normalizedDisplayName });
        await setDoc(
          doc(db, "users", credential.user.uid),
          {
            display_name: normalizedDisplayName,
            email: credential.user.email ?? email.trim(),
            role: "staff",
            default_branch_id: defaultBranchId,
            created_at: new Date().toISOString()
          },
          { merge: true }
        );
      } catch (profileError) {
        // Do not rollback auth user. Keep the account and allow login.
        // Admin can backfill Firestore profile later if needed.
        console.warn("Profile setup failed after signup:", profileError);
      }

      router.replace("/dashboard/upload-receipt");
    } catch (err) {
      const code =
        typeof err === "object" && err && "code" in err
          ? String((err as { code?: string }).code)
          : err instanceof Error
            ? err.message
            : "unknown";

      setError(getSignupErrorMessage(code));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Create account</CardTitle>
          <CardDescription>Sign up for The 49 Smart P&L.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="space-y-2">
              <Label htmlFor="display_name">Display name</Label>
              <Input
                id="display_name"
                type="text"
                autoComplete="name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="default_branch_id">Default Store</Label>
              <select
                id="default_branch_id"
                className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={defaultBranchId}
                onChange={(event) => setDefaultBranchId(event.target.value)}
                required
                disabled={submitting}
              >
                {BRANCH_OPTIONS.map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm_password">Confirm password</Label>
              <Input
                id="confirm_password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
              />
            </div>

            {error ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            ) : null}

            <Button type="submit" className="w-full" disabled={submitting || loading}>
              <UserPlus className="mr-2 h-4 w-4" />
              {submitting ? "Creating account..." : "Sign up"}
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-slate-600">
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-slate-900 underline">
              Sign in
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
