import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(
    { lineLiffId: process.env.LINE_LIFF_ID ?? null },
    { headers: { "Cache-Control": "no-store" } }
  );
}
