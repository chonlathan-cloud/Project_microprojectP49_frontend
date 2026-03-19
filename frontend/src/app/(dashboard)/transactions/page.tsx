"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCcw } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { TransactionTable } from "@/components/TransactionTable";
import { useAuth } from "@/components/providers/auth-provider";
import { useBranches } from "@/components/providers/branch-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import api from "@/lib/api";
import type { Branch } from "@/types/branch";
import type { Transaction } from "@/types/transaction";

type TransactionsResponse = {
  transactions: Transaction[];
  total: number;
  limit: number;
  offset: number;
};

type TransactionFilters = {
  startDate: string;
  endDate: string;
  transactionType: string;
  source: string;
  categoryId: string;
};

const COFFEE_CATEGORIES = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"];
const RESTAURANT_CATEGORIES = ["F1", "F2", "F3", "F4", "F5", "F6", "F7"];

function getCategoryOptions(branchType: Branch["type"] | undefined): string[] {
  if (branchType === "COFFEE") {
    return COFFEE_CATEGORIES;
  }
  if (branchType === "RESTAURANT") {
    return RESTAURANT_CATEGORIES;
  }
  return [];
}

function parsePositiveInt(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function parseNonNegativeInt(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
}

function normalizeTransactionType(value: string | null): string {
  const normalized = (value || "").trim().toUpperCase();
  return normalized === "EXPENSE" || normalized === "REVENUE" ? normalized : "";
}

function normalizeSource(value: string | null): string {
  const normalized = (value || "").trim().toUpperCase();
  return normalized === "OCR" || normalized === "POS_FILE" ? normalized : "";
}

function normalizeCategoryId(value: string | null): string {
  return (value || "").trim().toUpperCase();
}

function getErrorMessage(error: unknown): string {
  if (
    typeof error === "object" &&
    error &&
    "response" in error &&
    typeof (error as { response?: { data?: { detail?: unknown }; status?: number } }).response ===
      "object"
  ) {
    const response = (error as { response?: { data?: { detail?: unknown }; status?: number } })
      .response;

    if (response?.status === 404) {
      return "Transaction endpoint is not available yet on the backend.";
    }

    const detail = response?.data?.detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }

  return "Unable to load transactions. Please try again.";
}

function normalizeTransaction(transaction: Transaction): Transaction {
  return {
    ...transaction,
    amount: Number(transaction.amount) || 0
  };
}

function normalizeTransactions(payload: TransactionsResponse): Transaction[] {
  return (payload.transactions || []).map(normalizeTransaction);
}

async function fetchTransactions(
  branchId: string,
  limit: number,
  offset: number,
  filters: TransactionFilters
): Promise<TransactionsResponse> {
  const response = await api.get<TransactionsResponse>("/api/v1/transactions", {
    params: {
      branch_id: branchId,
      limit,
      offset,
      start_date: filters.startDate || undefined,
      end_date: filters.endDate || undefined,
      type: filters.transactionType || undefined,
      source: filters.source || undefined,
      category_id: filters.categoryId || undefined
    }
  });

  return {
    ...response.data,
    transactions: normalizeTransactions(response.data)
  };
}

export default function TransactionsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { profile } = useAuth();
  const {
    branches,
    loading: isLoadingBranches,
    error: branchError,
    refresh: refreshBranches
  } = useBranches();
  const normalizedRole = String(profile?.role || "staff").toLowerCase();
  const canSelectAnyBranch = normalizedRole === "admin" || normalizedRole === "executive";
  const defaultBranchId =
    typeof profile?.default_branch_id === "string" ? profile.default_branch_id.trim() : "";

  const [selectedBranchId, setSelectedBranchId] = useState(() => searchParams.get("branch_id") || "");
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [totalTransactions, setTotalTransactions] = useState(0);
  const [isLoadingTransactions, setIsLoadingTransactions] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [limit, setLimit] = useState(() => parsePositiveInt(searchParams.get("limit"), 100));
  const [offset, setOffset] = useState(() => parseNonNegativeInt(searchParams.get("offset"), 0));
  const [startDate, setStartDate] = useState(() => searchParams.get("start_date") || "");
  const [endDate, setEndDate] = useState(() => searchParams.get("end_date") || "");
  const [transactionType, setTransactionType] = useState(() =>
    normalizeTransactionType(searchParams.get("type"))
  );
  const [source, setSource] = useState(() => normalizeSource(searchParams.get("source")));
  const [selectedCategoryId, setSelectedCategoryId] = useState(() =>
    normalizeCategoryId(searchParams.get("category_id"))
  );

  useEffect(() => {
    if (branches.length === 0) {
      return;
    }

    const hasCurrentBranch = branches.some((branch) => branch.id === selectedBranchId);
    let nextBranchId = hasCurrentBranch ? selectedBranchId : "";

    if (canSelectAnyBranch) {
      if (!hasCurrentBranch) {
        const branchIdFromQuery = searchParams.get("branch_id");
        const lastBranchId =
          typeof window !== "undefined"
            ? window.localStorage.getItem("last_selected_branch_id")
            : null;
        const hasQueryBranch =
          !!branchIdFromQuery && branches.some((branch) => branch.id === branchIdFromQuery);
        const hasLastBranch =
          !!lastBranchId && branches.some((branch) => branch.id === lastBranchId);
        if (hasQueryBranch) {
          nextBranchId = branchIdFromQuery as string;
        } else if (hasLastBranch) {
          nextBranchId = lastBranchId as string;
        } else {
          nextBranchId = branches[0]?.id ?? "";
        }
      }
    } else {
      const hasDefaultBranch = !!defaultBranchId && branches.some((branch) => branch.id === defaultBranchId);
      nextBranchId = hasDefaultBranch ? defaultBranchId : branches[0]?.id ?? "";
    }

    if (nextBranchId && nextBranchId !== selectedBranchId) {
      setSelectedBranchId(nextBranchId);
      setOffset(0);
    }
  }, [branches, canSelectAnyBranch, defaultBranchId, searchParams, selectedBranchId]);

  const selectedBranch = useMemo(
    () => branches.find((branch) => branch.id === selectedBranchId) || null,
    [branches, selectedBranchId]
  );

  const categoryOptions = useMemo(
    () => getCategoryOptions(selectedBranch?.type),
    [selectedBranch?.type]
  );

  useEffect(() => {
    if (!selectedCategoryId) {
      return;
    }

    if (categoryOptions.length > 0 && !categoryOptions.includes(selectedCategoryId)) {
      setSelectedCategoryId("");
      setOffset(0);
    }
  }, [categoryOptions, selectedCategoryId]);

  useEffect(() => {
    if (isLoadingBranches) {
      return;
    }

    if (!selectedBranchId) {
      setTransactions([]);
      setTotalTransactions(0);
      return;
    }

    if (startDate && endDate && startDate > endDate) {
      setTransactions([]);
      setTotalTransactions(0);
      setError("Start date must be before or equal to end date.");
      return;
    }

    let isMounted = true;

    async function loadTransactions() {
      setIsLoadingTransactions(true);
      setError(null);

      try {
        const response = await fetchTransactions(selectedBranchId, limit, offset, {
          startDate,
          endDate,
          transactionType,
          source,
          categoryId: selectedCategoryId
        });
        if (!isMounted) {
          return;
        }

        setTransactions(response.transactions);
        setTotalTransactions(response.total);
        if (typeof window !== "undefined" && canSelectAnyBranch) {
          window.localStorage.setItem("last_selected_branch_id", selectedBranchId);
        }
      } catch (fetchError) {
        if (isMounted) {
          setTransactions([]);
          setTotalTransactions(0);
          setError(getErrorMessage(fetchError));
        }
      } finally {
        if (isMounted) {
          setIsLoadingTransactions(false);
        }
      }
    }

    void loadTransactions();
    return () => {
      isMounted = false;
    };
  }, [
    canSelectAnyBranch,
    endDate,
    isLoadingBranches,
    limit,
    offset,
    refreshKey,
    selectedBranchId,
    source,
    startDate,
    transactionType,
    selectedCategoryId
  ]);

  useEffect(() => {
    const params = new URLSearchParams();

    if (selectedBranchId) {
      params.set("branch_id", selectedBranchId);
    }
    if (startDate) {
      params.set("start_date", startDate);
    }
    if (endDate) {
      params.set("end_date", endDate);
    }
    if (transactionType) {
      params.set("type", transactionType);
    }
    if (source) {
      params.set("source", source);
    }
    if (selectedCategoryId) {
      params.set("category_id", selectedCategoryId);
    }
    if (limit !== 100) {
      params.set("limit", String(limit));
    }
    if (offset > 0) {
      params.set("offset", String(offset));
    }

    const nextQuery = params.toString();
    const currentQuery = searchParams.toString();
    if (nextQuery !== currentQuery) {
      router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname, { scroll: false });
    }
  }, [
    endDate,
    limit,
    offset,
    pathname,
    router,
    searchParams,
    selectedBranchId,
    selectedCategoryId,
    source,
    startDate,
    transactionType
  ]);

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(totalTransactions / limit));
  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + transactions.length < totalTransactions;
  const hasActiveFilters =
    !!startDate || !!endDate || !!transactionType || !!source || !!selectedCategoryId;

  return (
    <Card>
      <CardHeader className="gap-2">
        <CardTitle>Transactions</CardTitle>
        <CardDescription>
          Review transaction-level records, sort the current dataset, and export the visible rows to
          CSV or Excel.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="w-full max-w-sm space-y-2">
            <Label htmlFor="transaction-branch">Store</Label>
            {isLoadingBranches ? (
              <p className="flex h-10 items-center rounded-md border border-slate-200 bg-slate-50 px-3 text-sm text-slate-600">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Loading stores...
              </p>
            ) : branchError && branches.length === 0 ? (
              <div className="space-y-2">
                <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {branchError}
                </p>
                <Button type="button" variant="outline" onClick={refreshBranches}>
                  Retry
                </Button>
              </div>
            ) : branches.length === 0 ? (
              <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                No stores found. Configure branches before using transactions.
              </p>
            ) : (
              <select
                id="transaction-branch"
                className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={selectedBranchId}
                onChange={(event) => {
                  setSelectedBranchId(event.target.value);
                  setOffset(0);
                }}
                disabled={!canSelectAnyBranch || isLoadingTransactions}
              >
                {branches.map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name} ({branch.type})
                  </option>
                ))}
              </select>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="space-y-2">
              <Label htmlFor="transaction-limit">Rows per page</Label>
              <select
                id="transaction-limit"
                className="flex h-10 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={limit}
                onChange={(event) => {
                  setLimit(Number(event.target.value));
                  setOffset(0);
                }}
                disabled={isLoadingBranches || isLoadingTransactions}
              >
                {[50, 100, 200].map((pageSize) => (
                  <option key={pageSize} value={pageSize}>
                    {pageSize}
                  </option>
                ))}
              </select>
            </div>

            <Button
              type="button"
              variant="outline"
              onClick={() => setRefreshKey((current) => current + 1)}
              disabled={!selectedBranchId || isLoadingBranches || isLoadingTransactions}
            >
              {isLoadingTransactions ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCcw className="mr-2 h-4 w-4" />
              )}
              Refresh
            </Button>
          </div>
        </div>

        <div className="grid gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4 md:grid-cols-2 xl:grid-cols-6">
          <div className="space-y-2">
            <Label htmlFor="transaction-start-date">Start Date</Label>
            <input
              id="transaction-start-date"
              type="date"
              className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={startDate}
              onChange={(event) => {
                setStartDate(event.target.value);
                setOffset(0);
              }}
              disabled={isLoadingTransactions}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="transaction-end-date">End Date</Label>
            <input
              id="transaction-end-date"
              type="date"
              className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={endDate}
              onChange={(event) => {
                setEndDate(event.target.value);
                setOffset(0);
              }}
              disabled={isLoadingTransactions}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="transaction-type">Type</Label>
            <select
              id="transaction-type"
              className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={transactionType}
              onChange={(event) => {
                setTransactionType(event.target.value);
                setOffset(0);
              }}
              disabled={isLoadingTransactions}
            >
              <option value="">All types</option>
              <option value="EXPENSE">EXPENSE</option>
              <option value="REVENUE">REVENUE</option>
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="transaction-category">Category</Label>
            <select
              id="transaction-category"
              className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={selectedCategoryId}
              onChange={(event) => {
                setSelectedCategoryId(event.target.value);
                setOffset(0);
              }}
              disabled={isLoadingTransactions || categoryOptions.length === 0}
            >
              <option value="">
                {categoryOptions.length === 0 ? "Select branch first" : "All categories"}
              </option>
              {categoryOptions.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="transaction-source">Source</Label>
            <select
              id="transaction-source"
              className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={source}
              onChange={(event) => {
                setSource(event.target.value);
                setOffset(0);
              }}
              disabled={isLoadingTransactions}
            >
              <option value="">All sources</option>
              <option value="OCR">OCR</option>
              <option value="POS_FILE">POS_FILE</option>
            </select>
          </div>

          <div className="flex items-end">
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => {
                setStartDate("");
                setEndDate("");
                setTransactionType("");
                setSource("");
                setSelectedCategoryId("");
                setOffset(0);
              }}
              disabled={isLoadingTransactions || !hasActiveFilters}
            >
              Clear Filters
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 lg:flex-row lg:items-center lg:justify-between">
          <p>
            Page {currentPage} of {totalPages} • {totalTransactions} total transactions
          </p>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setOffset((current) => Math.max(0, current - limit))}
              disabled={!hasPreviousPage || isLoadingTransactions}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOffset((current) => current + limit)}
              disabled={!hasNextPage || isLoadingTransactions}
            >
              Next
            </Button>
          </div>
        </div>

        {error ? (
          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        ) : null}

        <TransactionTable
          transactions={transactions}
          isLoading={isLoadingTransactions && transactions.length === 0}
          totalCount={totalTransactions}
        />
      </CardContent>
    </Card>
  );
}
