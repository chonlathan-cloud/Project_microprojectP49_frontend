"use client";

import { useDeferredValue, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  FileSpreadsheet,
  FileText,
  Search
} from "lucide-react";
import * as XLSX from "xlsx";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Transaction } from "@/types/transaction";

type SortKey = keyof Transaction;
type SortDirection = "asc" | "desc";

type TransactionTableProps = {
  transactions: Transaction[];
  isLoading?: boolean;
  totalCount?: number;
};

type Column = {
  key: SortKey;
  label: string;
  className?: string;
};

type SortConfig = {
  key: SortKey;
  direction: SortDirection;
};

const columns: Column[] = [
  { key: "date", label: "Date", className: "min-w-[120px]" },
  { key: "branch_id", label: "Branch", className: "min-w-[120px]" },
  { key: "type", label: "Type", className: "min-w-[120px]" },
  { key: "category_id", label: "Category ID", className: "min-w-[120px]" },
  { key: "category_name", label: "Category Name", className: "min-w-[160px]" },
  { key: "item_name", label: "Item", className: "min-w-[180px]" },
  { key: "amount", label: "Amount", className: "min-w-[140px] text-right" },
  { key: "payment_method", label: "Payment", className: "min-w-[140px]" },
  { key: "source", label: "Source", className: "min-w-[120px]" },
  { key: "verified_by_user_id", label: "Verified By", className: "min-w-[180px]" },
  { key: "created_at", label: "Created At", className: "min-w-[180px]" }
];

const currencyFormatter = new Intl.NumberFormat("th-TH", {
  style: "currency",
  currency: "THB",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

const dateFormatter = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium"
});

const dateTimeFormatter = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short"
});

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : dateFormatter.format(parsed);
}

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : dateTimeFormatter.format(parsed);
}

function formatCellValue(transaction: Transaction, key: SortKey): string {
  const value = transaction[key];

  if (value === null || value === "") {
    return "—";
  }

  if (key === "amount") {
    return currencyFormatter.format(Number(value) || 0);
  }

  if (key === "date" && typeof value === "string") {
    return formatDate(value);
  }

  if (key === "created_at" && typeof value === "string") {
    return formatDateTime(value);
  }

  return String(value);
}

function getComparableValue(transaction: Transaction, key: SortKey): number | string | null {
  const value = transaction[key];

  if (value === null || value === "") {
    return null;
  }

  if (key === "amount") {
    return Number(value) || 0;
  }

  if ((key === "date" || key === "created_at") && typeof value === "string") {
    const timestamp = new Date(value).getTime();
    return Number.isNaN(timestamp) ? value.toLowerCase() : timestamp;
  }

  return String(value).toLowerCase();
}

function escapeCsvValue(value: string): string {
  const normalized = value.replaceAll('"', '""');
  return /[",\n]/.test(normalized) ? `"${normalized}"` : normalized;
}

function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function buildExportRows(transactions: Transaction[]): Record<string, string | number>[] {
  return transactions.map((transaction) => ({
    Date: formatCellValue(transaction, "date"),
    Branch: formatCellValue(transaction, "branch_id"),
    Type: formatCellValue(transaction, "type"),
    "Category ID": formatCellValue(transaction, "category_id"),
    "Category Name": formatCellValue(transaction, "category_name"),
    Item: formatCellValue(transaction, "item_name"),
    Amount: Number(transaction.amount) || 0,
    Payment: formatCellValue(transaction, "payment_method"),
    Source: formatCellValue(transaction, "source"),
    "Verified By": formatCellValue(transaction, "verified_by_user_id"),
    "Created At": formatCellValue(transaction, "created_at")
  }));
}

function getExportFileName(extension: "csv" | "xlsx"): string {
  const stamp = new Date().toISOString().slice(0, 10);
  return `transactions-${stamp}.${extension}`;
}

export function TransactionTable({
  transactions,
  isLoading = false,
  totalCount
}: TransactionTableProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [sortConfig, setSortConfig] = useState<SortConfig>({
    key: "created_at",
    direction: "desc"
  });

  const deferredSearchQuery = useDeferredValue(searchQuery);

  const filteredTransactions = useMemo(() => {
    const normalizedQuery = deferredSearchQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return transactions;
    }

    return transactions.filter((transaction) =>
      columns.some(({ key }) =>
        formatCellValue(transaction, key).toLowerCase().includes(normalizedQuery)
      )
    );
  }, [deferredSearchQuery, transactions]);

  const sortedTransactions = useMemo(() => {
    const nextTransactions = [...filteredTransactions];

    nextTransactions.sort((left, right) => {
      const leftValue = getComparableValue(left, sortConfig.key);
      const rightValue = getComparableValue(right, sortConfig.key);

      if (leftValue === null && rightValue === null) {
        return 0;
      }
      if (leftValue === null) {
        return 1;
      }
      if (rightValue === null) {
        return -1;
      }
      if (leftValue < rightValue) {
        return sortConfig.direction === "asc" ? -1 : 1;
      }
      if (leftValue > rightValue) {
        return sortConfig.direction === "asc" ? 1 : -1;
      }
      return 0;
    });

    return nextTransactions;
  }, [filteredTransactions, sortConfig]);

  function handleSort(key: SortKey) {
    setSortConfig((current) => {
      if (current.key === key) {
        return {
          key,
          direction: current.direction === "asc" ? "desc" : "asc"
        };
      }

      return {
        key,
        direction: key === "created_at" ? "desc" : "asc"
      };
    });
  }

  function handleExportCsv() {
    const exportRows = buildExportRows(sortedTransactions);
    const headers = Object.keys(exportRows[0] || buildExportRows(transactions)[0] || {});
    if (headers.length === 0) {
      return;
    }

    const csvLines = [
      headers.join(","),
      ...exportRows.map((row) => headers.map((header) => escapeCsvValue(String(row[header] ?? ""))).join(","))
    ];

    downloadBlob(
      new Blob(["\uFEFF", csvLines.join("\n")], { type: "text/csv;charset=utf-8;" }),
      getExportFileName("csv")
    );
  }

  function handleExportXlsx() {
    const exportRows = buildExportRows(sortedTransactions);
    if (exportRows.length === 0) {
      return;
    }

    const workbook = XLSX.utils.book_new();
    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    XLSX.utils.book_append_sheet(workbook, worksheet, "Transactions");

    const buffer = XLSX.write(workbook, { bookType: "xlsx", type: "array" });
    downloadBlob(
      new Blob([buffer], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      }),
      getExportFileName("xlsx")
    );
  }

  function renderSortIcon(key: SortKey) {
    if (sortConfig.key !== key) {
      return <ArrowUpDown className="h-4 w-4 text-slate-400" />;
    }

    return sortConfig.direction === "asc" ? (
      <ArrowUp className="h-4 w-4 text-slate-700" />
    ) : (
      <ArrowDown className="h-4 w-4 text-slate-700" />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search by branch, category, payment method, source..."
            className="pl-9"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={handleExportCsv}
            disabled={sortedTransactions.length === 0}
          >
            <FileText className="mr-2 h-4 w-4" />
            Export CSV
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={handleExportXlsx}
            disabled={sortedTransactions.length === 0}
          >
            <FileSpreadsheet className="mr-2 h-4 w-4" />
            Export Excel
          </Button>
        </div>
      </div>

      <div className="flex items-center justify-between text-sm text-slate-600">
        <p>
          Showing {sortedTransactions.length} rows on this page of {totalCount ?? transactions.length} total
        </p>
        <p>
          Sorted by <span className="font-medium text-slate-900">{sortConfig.key}</span> (
          {sortConfig.direction})
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200">
        <div className="max-h-[65vh] overflow-auto">
          <table className="min-w-full divide-y divide-slate-200 bg-white text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50">
              <tr>
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={`whitespace-nowrap px-4 py-3 text-left font-semibold text-slate-700 ${column.className ?? ""}`}
                  >
                    <button
                      type="button"
                      onClick={() => handleSort(column.key)}
                      className="inline-flex items-center gap-2"
                    >
                      <span>{column.label}</span>
                      {renderSortIcon(column.key)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-12 text-center text-slate-500">
                    Loading transactions...
                  </td>
                </tr>
              ) : sortedTransactions.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-12 text-center text-slate-500">
                    No transactions match the current view.
                  </td>
                </tr>
              ) : (
                sortedTransactions.map((transaction, index) => (
                  <tr key={`${transaction.created_at}-${transaction.branch_id}-${transaction.item_name ?? "row"}-${index}`} className="hover:bg-slate-50">
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={`whitespace-nowrap px-4 py-3 text-slate-700 ${column.className ?? ""}`}
                      >
                        {formatCellValue(transaction, column.key)}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
