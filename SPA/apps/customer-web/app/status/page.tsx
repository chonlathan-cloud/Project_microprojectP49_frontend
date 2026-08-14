"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

export default function StatusPage() {
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("t");
    queueMicrotask(() => setHasToken(Boolean(token)));
    window.history.replaceState({}, "", window.location.pathname);
  }, []);

  return (
    <main className="status-page">
      <section className="status-card" aria-labelledby="status-title">
        <span className="lotus-mark" aria-hidden="true">✦</span>
        <p className="eyebrow">SPA 49 • SECURE STATUS</p>
        <h1 id="status-title">ตรวจสอบสถานะการจอง</h1>
        <p className="english-subtitle">Check your booking status</p>
        {hasToken ? (
          <div className="notice notice-warning" role="status">
            The secure token was removed from the address bar. Status resolution will be enabled when the SPA API is connected.
          </div>
        ) : (
          <div className="notice" role="status">
            เปิดลิงก์ที่ร้านส่งให้เพื่อดูสถานะ โดยลิงก์จะไม่แสดงข้อมูลสุขภาพของคุณ
          </div>
        )}
        <Link className="primary-button inline-button" href="/">กลับไปหน้าจอง / Back to booking</Link>
      </section>
    </main>
  );
}
