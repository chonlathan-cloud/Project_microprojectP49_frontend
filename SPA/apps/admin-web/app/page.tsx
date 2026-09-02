"use client";

import { AdminDashboard } from "@/components/admin-dashboard";
import { AdminAuth } from "@/components/admin-auth";
import { AdminFeedbackProvider } from "@/components/admin-feedback";

export default function HomePage() {
  return <AdminFeedbackProvider><AdminAuth>{(user, logout) => <AdminDashboard user={user} onSignOut={logout} />}</AdminAuth></AdminFeedbackProvider>;
}
