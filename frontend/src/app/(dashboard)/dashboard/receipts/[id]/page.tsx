"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, Loader2, Plus, Send, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import api from "@/lib/api";

type AdjustmentType = "discount" | "service_charge" | "rounding" | "other";
type PaymentMethod = "CASH" | "TRANSFER";

type ReceiptItem = {
  id?: string;
  description: string;
  amount: number;
  category_id?: string | null;
};

type ReceiptAdjustment = {
  id?: string;
  type: AdjustmentType;
  label: string;
  amount: number;
};

type ReceiptHeader = {
  merchant?: string | null;
  date?: string | null;
  total?: number;
  vat?: number;
};

type CategoryOption = {
  id: string;
  name: string;
};

type ReceiptParty = {
  brand_name?: string | null;
  legal_name?: string | null;
  branch_name?: string | null;
  tax_id?: string | null;
  contact_person?: string | null;
  email?: string | null;
  phone?: string | null;
  address?: string | null;
};

type ReceiptDetail = {
  id: string;
  branch_id: string;
  branch_type?: "COFFEE" | "RESTAURANT";
  image_url?: string;
  image_preview_url?: string | null;
  flowaccount_synced?: boolean;
  flowaccount_document_serial?: string | null;
  flowaccount_attachment_synced?: boolean;
  flowaccount_payment_method?: PaymentMethod | null;
  flowaccount_bank_account_id?: number | null;
  flowaccount_bank_account_label?: string | null;
  seller?: ReceiptParty | null;
  buyer?: ReceiptParty | null;
  OCRbyGemini?: {
    seller?: ReceiptParty | null;
    buyer?: ReceiptParty | null;
  } | null;
  header?: ReceiptHeader;
  items: ReceiptItem[];
  adjustments?: ReceiptAdjustment[];
  allowed_categories?: CategoryOption[];
};

type FlowAccountBankAccount = {
  bank_account_id: number;
  bank_id: number;
  bank_name: string;
  bank_account_name: string;
  bank_account_number_masked: string;
  bank_account_type: number;
  bank_branch: string;
  label: string;
};

type EditableItem = {
  description: string;
  amount: string;
  category_id: string;
};

type EditableAdjustment = {
  type: AdjustmentType;
  label: string;
  amount: string;
};

type EditableParty = {
  legal_name: string;
  branch_name: string;
  tax_id: string;
  contact_person: string;
  email: string;
  phone: string;
  address: string;
};

type VerificationPayload = {
  items: {
    description: string;
    amount: number;
    category_id: string;
  }[];
  adjustments: {
    type: AdjustmentType;
    label: string;
    amount: number;
  }[];
  total_check: number;
  seller: EditableParty;
};

const COFFEE_CATEGORY_OPTIONS: CategoryOption[] = [
  { id: "C1", name: "COGS (วัตถุดิบ)" },
  { id: "C2", name: "Labor (ค่าแรง)" },
  { id: "C3", name: "Rent & Place (สถานที่)" },
  { id: "C4", name: "Utilities (สาธารณูปโภค)" },
  { id: "C5", name: "Equip & Maint (อุปกรณ์)" },
  { id: "C6", name: "System & Sales (ระบบ)" },
  { id: "C7", name: "Marketing (การตลาด)" },
  { id: "C8", name: "Admin (ทั่วไป)" },
  { id: "C9", name: "Reserve (สำรองจ่าย)" }
];

const RESTAURANT_CATEGORY_OPTIONS: CategoryOption[] = [
  { id: "F1", name: "Main Ingredients (วัตถุดิบหลัก)" },
  { id: "F2", name: "Labor (ค่าแรง)" },
  { id: "F3", name: "Fuel (เชื้อเพลิง)" },
  { id: "F4", name: "Containers (ภาชนะ)" },
  { id: "F5", name: "Water & Ice (น้ำ)" },
  { id: "F6", name: "Daily Waste (ของเสีย)" },
  { id: "F7", name: "Daily Misc (เบ็ดเตล็ด)" }
];

const ADJUSTMENT_TYPE_OPTIONS: { value: AdjustmentType; label: string }[] = [
  { value: "discount", label: "Discount" },
  { value: "service_charge", label: "Service Charge" },
  { value: "rounding", label: "Rounding" },
  { value: "other", label: "Other" }
];

function getFallbackCategoryOptions(
  branchType: ReceiptDetail["branch_type"]
): CategoryOption[] {
  if (branchType === "COFFEE") {
    return COFFEE_CATEGORY_OPTIONS;
  }
  return RESTAURANT_CATEGORY_OPTIONS;
}

function toEditableParty(party?: ReceiptParty | null): EditableParty {
  return {
    legal_name: party?.legal_name || party?.brand_name || "",
    branch_name: party?.branch_name || "",
    tax_id: party?.tax_id || "",
    contact_person: party?.contact_person || "",
    email: party?.email || "",
    phone: party?.phone || "",
    address: party?.address || ""
  };
}

function hasPartyValues(party?: ReceiptParty | null): boolean {
  if (!party) {
    return false;
  }
  return Object.values(party).some((value) => String(value || "").trim().length > 0);
}

function convertGsUriToHttps(uri?: string | null): string {
  if (!uri) {
    return "";
  }
  if (uri.startsWith("http://") || uri.startsWith("https://")) {
    return uri;
  }
  if (!uri.startsWith("gs://")) {
    return "";
  }
  const withoutScheme = uri.slice(5);
  const slashIndex = withoutScheme.indexOf("/");
  if (slashIndex === -1) {
    return "";
  }
  const bucket = withoutScheme.slice(0, slashIndex);
  const objectPath = withoutScheme.slice(slashIndex + 1);
  if (!bucket || !objectPath) {
    return "";
  }
  return `https://storage.googleapis.com/${bucket}/${objectPath}`;
}

function hasPdfExtension(uri?: string | null): boolean {
  if (!uri) {
    return false;
  }
  const clean = uri.split("?")[0].toLowerCase();
  return clean.endsWith(".pdf");
}

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

function getResponseStatus(error: unknown): number | null {
  if (
    typeof error === "object" &&
    error &&
    "response" in error &&
    typeof (error as { response?: { status?: unknown } }).response === "object"
  ) {
    const status = (error as { response?: { status?: unknown } }).response?.status;
    return typeof status === "number" ? status : null;
  }
  return null;
}

function getSignedAdjustmentAmount(adjustment: EditableAdjustment): number {
  const value = Number(adjustment.amount);
  if (!Number.isFinite(value)) {
    return 0;
  }
  return adjustment.type === "discount" ? -value : value;
}

export default function ReceiptValidationPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const receiptId = params?.id;

  const [receipt, setReceipt] = useState<ReceiptDetail | null>(null);
  const [items, setItems] = useState<EditableItem[]>([]);
  const [adjustments, setAdjustments] = useState<EditableAdjustment[]>([]);
  const [seller, setSeller] = useState<EditableParty>(() => toEditableParty(null));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncingToFlowAccount, setSyncingToFlowAccount] = useState(false);
  const [showResyncConfirm, setShowResyncConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [proxyImageUrl, setProxyImageUrl] = useState<string>("");
  const [proxyImageError, setProxyImageError] = useState<string | null>(null);
  const [proxyContentType, setProxyContentType] = useState<string | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("TRANSFER");
  const [bankAccounts, setBankAccounts] = useState<FlowAccountBankAccount[]>([]);
  const [selectedBankAccountId, setSelectedBankAccountId] = useState<string>("");
  const [bankAccountsLoading, setBankAccountsLoading] = useState(false);
  const [bankAccountsError, setBankAccountsError] = useState<string | null>(null);

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
        if (response.data.flowaccount_payment_method === "CASH") {
          setPaymentMethod("CASH");
        } else if (response.data.flowaccount_payment_method === "TRANSFER") {
          setPaymentMethod("TRANSFER");
        }
        if (response.data.flowaccount_bank_account_id) {
          setSelectedBankAccountId(String(response.data.flowaccount_bank_account_id));
        }
        const responseSeller = hasPartyValues(response.data.seller)
          ? response.data.seller
          : response.data.OCRbyGemini?.seller;
        setSeller(toEditableParty(responseSeller || null));
        setItems(
          (response.data.items || []).map((item) => ({
            description: item.description ?? "",
            amount: String(item.amount ?? 0),
            category_id: item.category_id ?? ""
          }))
        );
        setAdjustments(
          (response.data.adjustments || []).map((adjustment) => ({
            type: adjustment.type ?? "other",
            label: adjustment.label ?? "",
            amount: String(adjustment.amount ?? 0)
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

  useEffect(() => {
    let isMounted = true;

    async function fetchBankAccounts() {
      setBankAccountsLoading(true);
      setBankAccountsError(null);
      try {
        const response = await api.get<{ bank_accounts: FlowAccountBankAccount[] }>(
          "/api/v1/flowaccount/bank-accounts"
        );
        if (!isMounted) {
          return;
        }
        const accounts = response.data.bank_accounts || [];
        setBankAccounts(accounts);
        setSelectedBankAccountId((current) => {
          if (current || accounts.length === 0) {
            return current;
          }
          return String(accounts[0].bank_account_id);
        });
      } catch (fetchError) {
        if (isMounted) {
          setBankAccounts([]);
          setBankAccountsError(getErrorMessage(fetchError));
        }
      } finally {
        if (isMounted) {
          setBankAccountsLoading(false);
        }
      }
    }

    fetchBankAccounts();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!receiptId || !receipt?.image_url?.startsWith("gs://")) {
      setProxyImageUrl("");
      setProxyImageError(null);
      setProxyContentType(null);
      return;
    }

    let isMounted = true;
    let objectUrl = "";

    async function loadPreviewViaBackend() {
      try {
        setProxyImageError(null);
        const response = await api.get(`/api/v1/receipts/${receiptId}/preview`, {
          responseType: "blob"
        });
        if (!isMounted) {
          return;
        }
        objectUrl = URL.createObjectURL(response.data);
        setProxyImageUrl(objectUrl);
        const contentType = response.headers?.["content-type"];
        setProxyContentType(typeof contentType === "string" ? contentType : null);
      } catch {
        if (isMounted) {
          setProxyImageUrl("");
          setProxyImageError("Failed to load image via secure preview endpoint.");
          setProxyContentType(null);
        }
      }
    }

    loadPreviewViaBackend();

    return () => {
      isMounted = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [receiptId, receipt?.image_url]);

  const itemsTotal = useMemo(
    () =>
      items.reduce((sum, item) => {
        const value = Number(item.amount);
        return Number.isFinite(value) ? sum + value : sum;
      }, 0),
    [items]
  );

  const adjustmentsNet = useMemo(
    () => adjustments.reduce((sum, adjustment) => sum + getSignedAdjustmentAmount(adjustment), 0),
    [adjustments]
  );

  const total = useMemo(() => itemsTotal + adjustmentsNet, [adjustmentsNet, itemsTotal]);

  const categoryOptions = useMemo(() => {
    if (receipt?.allowed_categories && receipt.allowed_categories.length > 0) {
      return receipt.allowed_categories;
    }
    return getFallbackCategoryOptions(receipt?.branch_type);
  }, [receipt?.allowed_categories, receipt?.branch_type]);

  const allowedCategoryIds = useMemo(
    () => new Set(categoryOptions.map((category) => category.id)),
    [categoryOptions]
  );
  const selectedBankAccount = useMemo(
    () =>
      bankAccounts.find(
        (account) => String(account.bank_account_id) === selectedBankAccountId
      ) || null,
    [bankAccounts, selectedBankAccountId]
  );
  const isSubmitting = saving || syncingToFlowAccount;

  function updateItem(index: number, patch: Partial<EditableItem>) {
    setItems((prev) =>
      prev.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item))
    );
  }

  function addItem() {
    setItems((prev) => [...prev, { description: "", amount: "", category_id: "" }]);
  }

  function removeItem(index: number) {
    setItems((prev) => prev.filter((_, itemIndex) => itemIndex !== index));
  }

  function updateAdjustment(index: number, patch: Partial<EditableAdjustment>) {
    setAdjustments((prev) =>
      prev.map((adjustment, adjustmentIndex) =>
        adjustmentIndex === index ? { ...adjustment, ...patch } : adjustment
      )
    );
  }

  function addAdjustment() {
    setAdjustments((prev) => [...prev, { type: "discount", label: "", amount: "" }]);
  }

  function removeAdjustment(index: number) {
    setAdjustments((prev) =>
      prev.filter((_, adjustmentIndex) => adjustmentIndex !== index)
    );
  }

  function updateSeller(patch: Partial<EditableParty>) {
    setSeller((current) => ({ ...current, ...patch }));
  }

  function buildVerificationPayload(): VerificationPayload | null {
    if (items.length === 0) {
      setError("No line items found for verification.");
      return null;
    }

    const normalizedItems: VerificationPayload["items"] = [];
    for (const item of items) {
      const amount = Number(item.amount);
      if (!item.description.trim()) {
        setError("Each item must have a description.");
        return null;
      }
      if (!Number.isFinite(amount) || amount < 0) {
        setError("Each item must have a valid amount.");
        return null;
      }
      if (!item.category_id) {
        setError("Please select category for every item.");
        return null;
      }
      if (allowedCategoryIds.size > 0 && !allowedCategoryIds.has(item.category_id)) {
        setError("One or more selected categories are not allowed for this store.");
        return null;
      }
      normalizedItems.push({
        description: item.description.trim(),
        amount,
        category_id: item.category_id
      });
    }

    const normalizedAdjustments: VerificationPayload["adjustments"] = [];
    for (const adjustment of adjustments) {
      const amount = Number(adjustment.amount);
      if (!adjustment.label.trim()) {
        setError("Each adjustment must have a label.");
        return null;
      }
      if (!Number.isFinite(amount) || amount <= 0) {
        setError("Each adjustment must have a valid positive amount.");
        return null;
      }
      normalizedAdjustments.push({
        type: adjustment.type,
        label: adjustment.label.trim(),
        amount
      });
    }

    const sellerTaxDigits = seller.tax_id.replace(/\D/g, "");
    if (seller.tax_id.trim() && sellerTaxDigits.length !== 13) {
      setError("Dealer tax ID must contain 13 digits.");
      return null;
    }
    if (seller.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(seller.email.trim())) {
      setError("Dealer email must be a valid email address.");
      return null;
    }

    return {
      items: normalizedItems,
      adjustments: normalizedAdjustments,
      total_check: total,
      seller: {
        legal_name: seller.legal_name.trim(),
        branch_name: seller.branch_name.trim(),
        tax_id: sellerTaxDigits || "",
        contact_person: seller.contact_person.trim(),
        email: seller.email.trim(),
        phone: seller.phone.trim(),
        address: seller.address.trim()
      }
    };
  }

  async function handleVerifyAndSave() {
    if (!receiptId) {
      return;
    }

    const payload = buildVerificationPayload();
    if (!payload) {
      return;
    }

    setSaving(true);
    setError(null);

    try {
      await api.put(`/api/v1/receipts/${receiptId}/verify`, payload);
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

  async function handleVerifySaveAndSync(confirmResync = false) {
    if (!receiptId) {
      return;
    }

    const payload = buildVerificationPayload();
    if (!payload) {
      return;
    }

    if (paymentMethod === "TRANSFER" && !selectedBankAccount) {
      setError("Please select a transfer bank account before syncing to FlowAccount.");
      return;
    }

    setSyncingToFlowAccount(true);
    setError(null);
    setToastMessage(null);

    try {
      const response = await api.post(
        `/api/v1/receipts/${receiptId}/verify-and-sync-flowaccount`,
        {
          ...payload,
          confirm_resync: confirmResync,
          payment_method: paymentMethod,
          flowaccount_bank_account_id:
            paymentMethod === "TRANSFER" ? selectedBankAccount?.bank_account_id : undefined,
          flowaccount_transfer_bank_id:
            paymentMethod === "TRANSFER" ? selectedBankAccount?.bank_id : undefined,
          flowaccount_bank_account_label:
            paymentMethod === "TRANSFER" ? selectedBankAccount?.label : undefined
        }
      );
      const documentSerial =
        typeof response.data?.flowaccount_document_serial === "string"
          ? response.data.flowaccount_document_serial
          : "";
      setReceipt((current) =>
        current
          ? {
              ...current,
              flowaccount_synced: true,
              flowaccount_document_serial: documentSerial || current.flowaccount_document_serial,
              flowaccount_attachment_synced: Boolean(response.data?.flowaccount_attachment_synced),
              flowaccount_payment_method: paymentMethod,
              flowaccount_bank_account_id:
                paymentMethod === "TRANSFER" ? selectedBankAccount?.bank_account_id : null,
              flowaccount_bank_account_label:
                paymentMethod === "TRANSFER" ? selectedBankAccount?.label : null
            }
          : current
      );
      setShowResyncConfirm(false);
      setToastMessage(
        documentSerial
          ? `Receipt saved and synced to FlowAccount document ${documentSerial}.`
          : "Receipt saved and synced to FlowAccount."
      );
    } catch (syncError) {
      if (getResponseStatus(syncError) === 409) {
        setShowResyncConfirm(true);
      } else {
        setError(getErrorMessage(syncError));
      }
    } finally {
      setSyncingToFlowAccount(false);
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

  const isGcsSource = Boolean(receipt?.image_url?.startsWith("gs://"));
  const imageUrl = isGcsSource
    ? proxyImageUrl
    : convertGsUriToHttps(receipt?.image_preview_url) || convertGsUriToHttps(receipt?.image_url);
  const canPreviewMedia =
    imageUrl.startsWith("http://") ||
    imageUrl.startsWith("https://") ||
    imageUrl.startsWith("blob:");
  const isPdf =
    Boolean(proxyContentType?.toLowerCase().includes("pdf")) ||
    hasPdfExtension(receipt?.image_preview_url) ||
    hasPdfExtension(receipt?.image_url);

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

      {showResyncConfirm ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
          <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-5 shadow-xl">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-600" />
              <div className="space-y-2">
                <h3 className="text-base font-semibold text-slate-900">
                  Create another FlowAccount document?
                </h3>
                <p className="text-sm text-slate-600">
                  This receipt has already been synced to FlowAccount. Creating another document may
                  duplicate the expense in FlowAccount.
                </p>
              </div>
            </div>
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="outline"
                onClick={() => setShowResyncConfirm(false)}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={() => handleVerifySaveAndSync(true)}
                disabled={isSubmitting}
              >
                {syncingToFlowAccount ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Syncing...
                  </>
                ) : (
                  "Create New FlowAccount Document"
                )}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <h2 className="text-xl font-semibold text-slate-900">Receipt Validation</h2>

      <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
        <p className="font-medium text-slate-900">Store (locked for this receipt)</p>
        <p className="mt-1">
          {receipt?.branch_id || "-"} - This receipt cannot be split or reassigned to another store.
        </p>
        <p className="mt-1 text-xs text-slate-500">Business type: {receipt?.branch_type || "-"}</p>
      </div>

      {receipt?.flowaccount_synced ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <p className="flex items-center gap-2 font-medium">
            <CheckCircle2 className="h-4 w-4" />
            Synced to FlowAccount
          </p>
          <p className="mt-1 text-emerald-700">
            Document: {receipt.flowaccount_document_serial || "-"} - Attachment:{" "}
            {receipt.flowaccount_attachment_synced ? "synced" : "not synced"}
          </p>
          {receipt.flowaccount_payment_method ? (
            <p className="mt-1 text-emerald-700">
              Payment: {receipt.flowaccount_payment_method}
              {receipt.flowaccount_bank_account_label
                ? ` - ${receipt.flowaccount_bank_account_label}`
                : ""}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-3 rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 md:grid-cols-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Merchant</p>
          <p className="font-medium text-slate-900">{receipt?.header?.merchant || "-"}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Date</p>
          <p className="font-medium text-slate-900">{receipt?.header?.date || "-"}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Total</p>
          <p className="font-medium text-slate-900">
            {Number(receipt?.header?.total || 0).toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">VAT</p>
          <p className="font-medium text-slate-900">
            {Number(receipt?.header?.vat || 0).toFixed(2)}
          </p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Receipt Image</CardTitle>
          </CardHeader>
          <CardContent>
            {canPreviewMedia ? (
              isPdf ? (
                <object
                  data={imageUrl}
                  type="application/pdf"
                  className="h-[70vh] w-full rounded-lg border border-slate-200"
                >
                  <p className="text-sm text-slate-600">
                    PDF preview is unavailable in this browser.
                  </p>
                </object>
              ) : (
                <img
                  src={imageUrl}
                  alt={`Receipt ${receiptId}`}
                  className="w-full rounded-lg border border-slate-200 object-contain"
                />
              )
            ) : (
              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
                <p>
                  {isGcsSource
                    ? "Image preview is currently unavailable via secure proxy."
                    : "Image preview is unavailable for this URI type."}
                </p>
                {proxyImageError ? (
                  <p className="mt-2 text-xs text-red-600">{proxyImageError}</p>
                ) : null}
                <p className="mt-2 break-all font-mono text-xs text-slate-500">
                  {receipt?.image_url || "No image URL provided."}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle>Extracted Items</CardTitle>
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" size="sm" onClick={addItem} disabled={isSubmitting}>
                <Plus className="mr-2 h-4 w-4" />
                Add Item
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addAdjustment}
                disabled={isSubmitting}
              >
                <Plus className="mr-2 h-4 w-4" />
                Add Adjustment
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {items.length === 0 ? (
              <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                No extracted items yet. Click Add Item to insert a line.
              </p>
            ) : (
              <div className="space-y-4">
                {items.map((item, index) => (
                  <div key={`item-${index}`} className="rounded-lg border border-slate-200 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <p className="text-sm font-medium text-slate-700">Line Item {index + 1}</p>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => removeItem(index)}
                        disabled={isSubmitting}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>

                    <div className="grid gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor={`description-${index}`}>Description</Label>
                        <Input
                          id={`description-${index}`}
                          value={item.description}
                          onChange={(event) =>
                            updateItem(index, { description: event.target.value })
                          }
                          disabled={isSubmitting}
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
                            disabled={isSubmitting}
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
                            disabled={isSubmitting}
                          >
                            <option value="">Select category</option>
                            {categoryOptions.map((category) => (
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
            )}

            <div className="space-y-3 rounded-lg border border-slate-200 p-4">
              <div>
                <p className="text-sm font-medium text-slate-900">Adjustments</p>
                <p className="text-xs text-slate-500">
                  Use this for discounts, service charge, or rounding. Discounts stay
                  positive here and are subtracted from the final total.
                </p>
              </div>

              {adjustments.length === 0 ? (
                <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                  No adjustments yet. Click Add Adjustment when the receipt includes
                  discount or other receipt-level adjustments.
                </p>
              ) : (
                <div className="space-y-3">
                  {adjustments.map((adjustment, index) => (
                    <div
                      key={`adjustment-${index}`}
                      className="rounded-lg border border-slate-200 p-4"
                    >
                      <div className="mb-3 flex items-center justify-between">
                        <p className="text-sm font-medium text-slate-700">
                          Adjustment {index + 1}
                        </p>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => removeAdjustment(index)}
                          disabled={isSubmitting}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>

                      <div className="grid gap-3 md:grid-cols-3">
                        <div className="space-y-1.5">
                          <Label htmlFor={`adjustment-type-${index}`}>Type</Label>
                          <select
                            id={`adjustment-type-${index}`}
                            className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                            value={adjustment.type}
                            onChange={(event) =>
                              updateAdjustment(index, {
                                type: event.target.value as AdjustmentType
                              })
                            }
                            disabled={isSubmitting}
                          >
                            {ADJUSTMENT_TYPE_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="space-y-1.5 md:col-span-2">
                          <Label htmlFor={`adjustment-label-${index}`}>Label</Label>
                          <Input
                            id={`adjustment-label-${index}`}
                            value={adjustment.label}
                            onChange={(event) =>
                              updateAdjustment(index, { label: event.target.value })
                            }
                            disabled={isSubmitting}
                          />
                        </div>
                      </div>

                      <div className="mt-3 max-w-xs space-y-1.5">
                        <Label htmlFor={`adjustment-amount-${index}`}>Amount</Label>
                        <Input
                          id={`adjustment-amount-${index}`}
                          type="number"
                          step="0.01"
                          value={adjustment.amount}
                          onChange={(event) =>
                            updateAdjustment(index, { amount: event.target.value })
                          }
                          disabled={isSubmitting}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-2 rounded-md bg-slate-100 px-3 py-3">
              <div className="flex items-center justify-between text-sm text-slate-700">
                <p>Items Total</p>
                <p className="font-medium text-slate-900">{itemsTotal.toFixed(2)}</p>
              </div>
              <div className="flex items-center justify-between text-sm text-slate-700">
                <p>Adjustments Net</p>
                <p className="font-medium text-slate-900">{adjustmentsNet.toFixed(2)}</p>
              </div>
              <div className="flex items-center justify-between border-t border-slate-200 pt-2">
                <p className="text-sm font-medium text-slate-700">Total Check</p>
                <p className="font-semibold text-slate-900">{total.toFixed(2)}</p>
              </div>
            </div>

            <div className="space-y-3 rounded-lg border border-slate-200 p-4">
              <p className="text-sm font-medium text-slate-900">Dealer Details</p>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="dealer-legal-name">Dealer Name</Label>
                  <Input
                    id="dealer-legal-name"
                    value={seller.legal_name}
                    onChange={(event) => updateSeller({ legal_name: event.target.value })}
                    disabled={isSubmitting}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="dealer-tax-id">Tax ID</Label>
                  <Input
                    id="dealer-tax-id"
                    value={seller.tax_id}
                    onChange={(event) => updateSeller({ tax_id: event.target.value })}
                    disabled={isSubmitting}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="dealer-branch-name">Branch</Label>
                  <Input
                    id="dealer-branch-name"
                    value={seller.branch_name}
                    onChange={(event) => updateSeller({ branch_name: event.target.value })}
                    disabled={isSubmitting}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="dealer-contact-person">Contact Person</Label>
                  <Input
                    id="dealer-contact-person"
                    value={seller.contact_person}
                    onChange={(event) => updateSeller({ contact_person: event.target.value })}
                    disabled={isSubmitting}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="dealer-email">Email</Label>
                  <Input
                    id="dealer-email"
                    type="email"
                    value={seller.email}
                    onChange={(event) => updateSeller({ email: event.target.value })}
                    disabled={isSubmitting}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="dealer-phone">Phone</Label>
                  <Input
                    id="dealer-phone"
                    value={seller.phone}
                    onChange={(event) => updateSeller({ phone: event.target.value })}
                    disabled={isSubmitting}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dealer-address">Address</Label>
                <textarea
                  id="dealer-address"
                  className="flex min-h-24 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                  value={seller.address}
                  onChange={(event) => updateSeller({ address: event.target.value })}
                  disabled={isSubmitting}
                />
              </div>
            </div>

            <div className="space-y-3 rounded-lg border border-slate-200 p-4">
              <p className="text-sm font-medium text-slate-900">FlowAccount Payment</p>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="flowaccount-payment-method">Payment Method</Label>
                  <select
                    id="flowaccount-payment-method"
                    className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    value={paymentMethod}
                    onChange={(event) => setPaymentMethod(event.target.value as PaymentMethod)}
                    disabled={isSubmitting}
                  >
                    <option value="TRANSFER">Transfer</option>
                    <option value="CASH">Cash</option>
                  </select>
                </div>

                {paymentMethod === "TRANSFER" ? (
                  <div className="space-y-1.5">
                    <Label htmlFor="flowaccount-bank-account">Bank Account</Label>
                    <select
                      id="flowaccount-bank-account"
                      className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                      value={selectedBankAccountId}
                      onChange={(event) => setSelectedBankAccountId(event.target.value)}
                      disabled={isSubmitting || bankAccountsLoading || bankAccounts.length === 0}
                    >
                      <option value="">
                        {bankAccountsLoading ? "Loading bank accounts" : "Select bank account"}
                      </option>
                      {bankAccounts.map((account) => (
                        <option key={account.bank_account_id} value={account.bank_account_id}>
                          {account.label}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
              </div>
              {paymentMethod === "TRANSFER" && bankAccountsError ? (
                <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                  {bankAccountsError}
                </p>
              ) : null}
            </div>

            {error ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            ) : null}

            <div className="flex flex-col gap-2 sm:flex-row">
              <Button type="button" disabled={isSubmitting} onClick={handleVerifyAndSave}>
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  "Verify & Save"
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={isSubmitting}
                onClick={() => handleVerifySaveAndSync(false)}
              >
                {syncingToFlowAccount ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving and syncing...
                  </>
                ) : (
                  <>
                    <Send className="mr-2 h-4 w-4" />
                    Verify, Save & Sync to FlowAccount
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
