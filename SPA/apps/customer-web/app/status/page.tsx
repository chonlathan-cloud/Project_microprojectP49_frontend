"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { loadLiff } from "@/lib/line-liff";

type StatusResult = {
  bookingId: string;
  status: string;
  localDate: string;
  localStartTime: string;
  estimatedAmountSatang: number;
};

const BOOKING_KEY = "spa49.lineLink.bookingId";
const TOKEN_KEY = "spa49.lineLink.statusToken";

export default function StatusPage() {
  const [result, setResult] = useState<StatusResult | null>(null);
  const [credentials, setCredentials] = useState<{ bookingId: string; statusToken: string } | null>(null);
  const [state, setState] = useState<"missing" | "loading" | "ready" | "error">("loading");
  const [linkState, setLinkState] = useState<"idle" | "linking" | "linked" | "error" | "unavailable">("idle");
  const [linkMessage, setLinkMessage] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const bookingId = params.get("id") ?? sessionStorage.getItem(BOOKING_KEY);
    const statusToken = params.get("t") ?? sessionStorage.getItem(TOKEN_KEY);
    window.history.replaceState({}, "", window.location.pathname);
    if (!bookingId || !statusToken) {
      queueMicrotask(() => setState("missing"));
      return;
    }
    sessionStorage.setItem(BOOKING_KEY, bookingId);
    sessionStorage.setItem(TOKEN_KEY, statusToken);
    queueMicrotask(() => setCredentials({ bookingId, statusToken }));
    fetch("/api/spa/api/v1/public/bookings/status:resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookingId, statusToken }),
      cache: "no-store"
    }).then(async (response) => {
      if (!response.ok) throw new Error("Invalid or expired status link");
      setResult(await response.json() as StatusResult);
      setState("ready");
    }).catch(() => setState("error"));
  }, []);

  async function connectLine() {
    if (!credentials || linkState === "linking") return;
    setLinkState("linking");
    setLinkMessage("");
    try {
      const configResponse = await fetch("/api/config", { cache: "no-store" });
      const config = await configResponse.json() as { lineLiffId?: string | null };
      if (!config.lineLiffId) {
        setLinkState("unavailable");
        return;
      }
      const liff = await loadLiff();
      await liff.init({ liffId: config.lineLiffId });
      if (!liff.isLoggedIn()) {
        liff.login({ redirectUri: window.location.href });
        return;
      }
      const lineIdToken = liff.getIDToken();
      if (!lineIdToken) throw new Error("LINE ID token is unavailable");
      const response = await fetch("/api/spa/api/v1/public/booking-line-links", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...credentials, lineIdToken }),
        cache: "no-store"
      });
      const payload = await response.json() as { linked?: boolean; detail?: string };
      if (!response.ok || !payload.linked) throw new Error(payload.detail ?? "LINE linking failed");
      sessionStorage.removeItem(BOOKING_KEY);
      sessionStorage.removeItem(TOKEN_KEY);
      setLinkState("linked");
      setLinkMessage("เชื่อม LINE สำเร็จแล้ว คุณจะได้รับการแจ้งเตือนเมื่อร้านยืนยันการจอง");
    } catch (caught) {
      setLinkState("error");
      setLinkMessage(caught instanceof Error ? caught.message : "LINE linking failed");
    }
  }

  return <main className="status-page"><section className="status-card" aria-labelledby="status-title">
    <p className="eyebrow">SPA 49 • SECURE STATUS</p>
    <h1 id="status-title">ตรวจสอบสถานะการจอง</h1>
    <p className="english-subtitle">Check your booking status</p>
    {state === "loading" && <div className="notice" role="status">กำลังตรวจสอบสถานะ…</div>}
    {state === "missing" && <div className="notice">กรุณาเปิด Secure Status Link ที่ร้านส่งให้</div>}
    {state === "error" && <div className="notice notice-warning" role="alert">ลิงก์ไม่ถูกต้องหรือหมดอายุ กรุณาติดต่อ 064-365-4949</div>}
    {state === "ready" && result && <div className="review-card" role="status">
      <p><strong>{result.bookingId}</strong></p>
      <p>สถานะ: <strong>{result.status}</strong></p>
      <p>{result.localDate} • {result.localStartTime}</p>
      <p>ราคาประเมินรวม: {(result.estimatedAmountSatang / 100).toLocaleString("th-TH")} บาท</p>
    </div>}
    {state === "ready" && linkState !== "linked" && <div className="line-link-panel">
      <h2>รับการแจ้งเตือนผ่าน LINE</h2>
      <p>เชื่อม Booking นี้กับ Customer LINE OA เพื่อรับข้อความเมื่อร้านยืนยันการจอง</p>
      <button className="primary-button line-link-button" onClick={connectLine} disabled={linkState === "linking"}>
        {linkState === "linking" ? "กำลังเชื่อม LINE…" : "เชื่อม LINE / Connect LINE"}
      </button>
      {linkState === "unavailable" && <p className="link-error" role="alert">LINE Login ยังไม่พร้อมใช้งาน กรุณาติดต่อร้าน</p>}
      {linkState === "error" && <p className="link-error" role="alert">{linkMessage}</p>}
    </div>}
    {linkState === "linked" && <div className="notice" role="status">{linkMessage}</div>}
    <Link className="primary-button inline-button" href="/">กลับไปหน้าจอง / Back to booking</Link>
  </section></main>;
}
