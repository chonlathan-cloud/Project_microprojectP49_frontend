"use client";

import { AdminDashboard } from "@/components/admin-dashboard";
import { AdminAuth } from "@/components/admin-auth";
import { AdminFeedbackProvider } from "@/components/admin-feedback";

export default function HomePage() {
  return <AdminFeedbackProvider><AdminAuth>{(user) => <AdminDashboard user={user} />}</AdminAuth></AdminFeedbackProvider>;
}
