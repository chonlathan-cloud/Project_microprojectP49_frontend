"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { CheckCircle2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import api from "@/lib/api";

type ReceiptItem = {
  id?: string;
  description: string;
  amount: number;
  category_id?: string | null;
};

type ReceiptDetail = {
  id: string;
  branch_id: string;
  image_url?: string;
  image_preview_url?: string | null;
  items: ReceiptItem[];
};

type EditableItem = {
  description: string;
  amount: string;
  category_id: string;
};

const CATEGORY_OPTIONS: Array<{ id: string; name: string }> = [
  { id: "C1", name: "COGS (วัตถุดิบ)" },
  { id: "C2", name: "Labor (ค่าแรง)" },
  { id: "C3", name: "Rent & Place (สถานที่)" },
  { id: "C4", name: "Utilities (สาธารณูปโภค)" },
  { id: "C5", name: "Equip & Maint (อุปกรณ์)" },
  { id: "C6", name: "System & Sales (ระบบ)" },
  { id: "C7", name: "Marketing (การตลาด)" },
  { id: "C8", name: "Admin (ทั่วไป)" },
  { id: "C9", name: "Reserve (สำรองจ่าย)" },
  { id: "F1", name: "Main Ingredients (วัตถุดิบหลัก)" },
  { id: "F2", name: "Labor (ค่าแรง)" },
  { id: "F3", name: "Fuel (เชื้อเพลิง)" },
  { id: "F4", name: "Containers (ภาชนะ)" },
  { id: "F5", name: "Water & Ice (น้ำ)" },
  { id: "F6", name: "Daily Waste (ของเสีย)" },
  { id: "F7", name: "Daily Misc (เบ็ดเตล็ด)" }
];

function getErrorMessage(error: unknown): string {
  if (
    typeof error === "object" &&
    error &&
    "response" in error &&
    typeof (error as { response?: { data?: { detail?: unknown } } }).response ===
      "object"
  ) {
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response
      ?.data?.detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }
  return "Request failed. Please try again.";
}

export default function ReceiptValidationPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const receiptId = params?.id;

  const [receipt, setReceipt] = useState<ReceiptDetail | null>(null);
  const [items, setItems] = useState<EditableItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!receiptId) {
      return;
    }

    let isMounted = true;

    async function fetchReceipt() {
      setLoading(true);
      setError(null);
      try {
        const response = await api.get<ReceiptDetail>(`/api/v1/receipts/${receiptId}`);
        if (!isMounted) {
          return;
        }
        setReceipt(response.data);
        setItems(
          (response.data.items || []).map((item) => ({
            description: item.description ?? "",
            amount: String(item.amount ?? 0),
            category_id: item.category_id ?? ""
          }))
        );
      } catch (fetchError) {
        if (!isMounted) {
          return;
        }
        setError(getErrorMessage(fetchError));
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    fetchReceipt();

    return () => {
      isMounted = false;
    };
  }, [receiptId]);

  const total = useMemo(
    () =>
      items.reduce((sum, item) => {
        const value = Number(item.amount);
        return Number.isFinite(value) ? sum + value : sum;
      }, 0),
    [items]
  );

  function updateItem(index: number, patch: Partial<EditableItem>) {
    setItems((prev) =>
      prev.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item))
    );
  }

  async function handleVerifyAndSave() {
    if (!receiptId) {
      return;
    }

    if (items.length === 0) {
      setError("No line items found for verification.");
      return;
    }

    const normalizedItems = [];
    for (const item of items) {
      const amount = Number(item.amount);
      if (!item.description.trim()) {
        setError("Each item must have a description.");
        return;
      }
      if (!Number.isFinite(amount) || amount < 0) {
        setError("Each item must have a valid amount.");
        return;
      }
      if (!item.category_id) {
        setError("Please select category for every item.");
        return;
      }
      normalizedItems.push({
        description: item.description.trim(),
        amount,
        category_id: item.category_id
      });
    }

    setSaving(true);
    setError(null);

    try {
      await api.put(`/api/v1/receipts/${receiptId}/verify`, {
        items: normalizedItems,
        total_check: total
      });
      setToastMessage("Receipt verified and saved successfully.");
      setTimeout(() => {
        router.push("/dashboard/upload-receipt");
      }, 900);
    } catch (verifyError) {
      setError(getErrorMessage(verifyError));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="flex items-center gap-2 text-sm text-slate-600">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading receipt...
        </p>
      </div>
    );
  }

  if (error && !receipt) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Receipt Validation</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        </CardContent>
      </Card>
    );
  }

  const imageUrl = receipt?.image_preview_url || receipt?.image_url || "";
  const canPreviewImage = imageUrl.startsWith("http://") || imageUrl.startsWith("https://");

  return (
    <div className="space-y-4">
      {toastMessage ? (
        <div className="fixed right-6 top-20 z-50 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 shadow-md">
          <p className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4" />
            {toastMessage}
          </p>
        </div>
      ) : null}

      <h2 className="text-xl font-semibold text-slate-900">Receipt Validation</h2>

      <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
        <p className="font-medium text-slate-900">Store (locked for this receipt)</p>
        <p className="mt-1">
          {receipt?.branch_id || "-"} - This receipt cannot be split or reassigned to another store.
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Receipt Image</CardTitle>
          </CardHeader>
          <CardContent>
            {canPreviewImage ? (
              <img
                src={imageUrl}
                alt={`Receipt ${receiptId}`}
                className="w-full rounded-lg border border-slate-200 object-contain"
              />
            ) : (
              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
                <p>Image preview is unavailable for this URI type.</p>
                <p className="mt-2 break-all font-mono text-xs text-slate-500">
                  {receipt?.image_url || "No image URL provided."}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Extracted Items</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-4">
              {items.map((item, index) => (
                <div key={`item-${index}`} className="rounded-lg border border-slate-200 p-4">
                  <div className="grid gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor={`description-${index}`}>Description</Label>
                      <Input
                        id={`description-${index}`}
                        value={item.description}
                        onChange={(event) =>
                          updateItem(index, { description: event.target.value })
                        }
                        disabled={saving}
                      />
                    </div>

                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label htmlFor={`amount-${index}`}>Amount</Label>
                        <Input
                          id={`amount-${index}`}
                          type="number"
                          step="0.01"
                          value={item.amount}
                          onChange={(event) =>
                            updateItem(index, { amount: event.target.value })
                          }
                          disabled={saving}
                        />
                      </div>

                      <div className="space-y-1.5">
                        <Label htmlFor={`category-${index}`}>Category</Label>
                        <select
                          id={`category-${index}`}
                          className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                          value={item.category_id}
                          onChange={(event) =>
                            updateItem(index, { category_id: event.target.value })
                          }
                          disabled={saving}
                        >
                          <option value="">Select category</option>
                          {CATEGORY_OPTIONS.map((category) => (
                            <option key={category.id} value={category.id}>
                              {category.id} - {category.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between rounded-md bg-slate-100 px-3 py-2">
              <p className="text-sm font-medium text-slate-700">Total Check</p>
              <p className="font-semibold text-slate-900">{total.toFixed(2)}</p>
            </div>

            {error ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            ) : null}

            <Button type="button" disabled={saving} onClick={handleVerifyAndSave}>
              {saving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                "Verify & Save"
              )}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
