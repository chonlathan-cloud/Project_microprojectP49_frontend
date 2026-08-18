import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const apiBaseUrl = (process.env.SPA_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
  if (!apiBaseUrl) {
    return NextResponse.json({ error: "SPA_API_URL is not configured" }, { status: 503 });
  }

  const target = `${apiBaseUrl}/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");

  const response = await fetch(target, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    cache: "no-store",
    // Required by Node's fetch when forwarding a streaming request body.
    ...(request.method === "GET" || request.method === "HEAD" ? {} : { duplex: "half" as const })
  });

  return new NextResponse(response.body, {
    status: response.status,
    headers: response.headers
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
