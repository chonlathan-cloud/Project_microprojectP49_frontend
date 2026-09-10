const WHOLE_BAHT_PATTERN = /^\d+$/;

export function settlementAmountDraft(satang: number): string {
  if (!Number.isFinite(satang) || satang === 0) return "";
  return String(satang / 100);
}

export function parseSettlementAmountDraft(value: string): number | null {
  const normalized = value.trim();
  if (normalized === "") return 0;
  if (!WHOLE_BAHT_PATTERN.test(normalized)) return null;

  const baht = Number(normalized);
  if (!Number.isSafeInteger(baht) || baht > Math.floor(Number.MAX_SAFE_INTEGER / 100)) return null;
  return baht * 100;
}
