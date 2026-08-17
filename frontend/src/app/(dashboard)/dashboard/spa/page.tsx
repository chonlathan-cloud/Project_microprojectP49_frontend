import { ExternalLink, Sparkles } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";

export const dynamic = "force-dynamic";

export default function SpaLauncherPage() {
  const spaAdminUrl = process.env.NEXT_PUBLIC_SPA_ADMIN_URL?.trim();

  return (
    <div className="mx-auto w-full max-w-3xl">
      <Card>
        <CardHeader>
          <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-lg bg-emerald-100 text-emerald-700">
            <Sparkles className="h-5 w-5" />
          </div>
          <CardTitle>SPA Booking &amp; Operations</CardTitle>
          <CardDescription>
            Open the separate SPA Admin application for bookings, capacity, therapists,
            and branch operations.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {spaAdminUrl ? (
            <a
              href={spaAdminUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-slate-900 px-4 text-sm font-medium text-white transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
            >
              Open SPA Admin
              <ExternalLink className="h-4 w-4" />
            </a>
          ) : (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              SPA Admin is not deployed or its URL has not been configured yet. Set
              {" "}
              <code className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs">
                NEXT_PUBLIC_SPA_ADMIN_URL
              </code>
              {" "}
              in the Receipt frontend environment after deploying
              {" "}
              <code className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs">
                spa-admin-web
              </code>
              .
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
