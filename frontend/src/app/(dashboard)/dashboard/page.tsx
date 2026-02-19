"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { Loader2, Sparkles } from "lucide-react";

import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import api from "@/lib/api";

type Branch = {
  id: string;
  name: string;
  type: "COFFEE" | "RESTAURANT";
};

type BranchListResponse = {
  branches: Branch[];
};

type ExpenseCategoryRow = {
  category_id: string;
  category_name: string;
  total: number;
};

type AnalyticsSummaryResponse = {
  total_revenue: number;
  total_expense: number;
  net_profit: number;
  food_cost_percent: number;
  top_expense_category: string | null;
  expense_by_category: ExpenseCategoryRow[];
};

type AiChatResponse = {
  answer: string;
  citations?: string[];
  kb_used?: boolean;
  fallback_mode?: "hybrid" | "bigquery_only";
};

const PIE_COLORS = ["#ef4444", "#f97316", "#f59e0b", "#22c55e", "#06b6d4", "#3b82f6", "#8b5cf6"];

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

function formatDateForInput(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function getDefaultDateRange(): { startDate: string; endDate: string } {
  const now = new Date();
  const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);

  return {
    startDate: formatDateForInput(startOfMonth),
    endDate: formatDateForInput(now)
  };
}

function toNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
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
      return "AI insight endpoint is not available yet on backend.";
    }

    const detail = response?.data?.detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }
  return "Request failed. Please try again.";
}

export default function DashboardPage() {
  const { profile } = useAuth();
  const defaultRange = getDefaultDateRange();
  const normalizedRole = String(profile?.role || "staff").toLowerCase();
  const canSelectAnyBranch = normalizedRole === "admin" || normalizedRole === "executive";
  const defaultBranchId =
    typeof profile?.default_branch_id === "string" ? profile.default_branch_id.trim() : "";

  const [branches, setBranches] = useState<Branch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [startDate, setStartDate] = useState(defaultRange.startDate);
  const [endDate, setEndDate] = useState(defaultRange.endDate);

  const [summary, setSummary] = useState<AnalyticsSummaryResponse | null>(null);
  const [isLoadingBranches, setIsLoadingBranches] = useState(true);
  const [isLoadingSummary, setIsLoadingSummary] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [question, setQuestion] = useState("");
  const [aiAnswer, setAiAnswer] = useState("");
  const [aiCitations, setAiCitations] = useState<string[]>([]);
  const [isAskingAi, setIsAskingAi] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadBranches() {
      setIsLoadingBranches(true);
      setError(null);
      try {
        const response = await api.get<BranchListResponse>("/api/v1/branches");
        if (!isMounted) {
          return;
        }

        const branchList = response.data.branches || [];
        setBranches(branchList);

        let nextBranchId = branchList[0]?.id ?? "";
        if (canSelectAnyBranch) {
          const lastBranchId =
            typeof window !== "undefined"
              ? window.localStorage.getItem("last_selected_branch_id")
              : null;
          const hasLastBranch =
            !!lastBranchId && branchList.some((branch) => branch.id === lastBranchId);
          nextBranchId = hasLastBranch ? (lastBranchId as string) : nextBranchId;
        } else if (defaultBranchId) {
          const hasDefaultBranch = branchList.some((branch) => branch.id === defaultBranchId);
          if (hasDefaultBranch) {
            nextBranchId = defaultBranchId;
          }
        }

        setSelectedBranchId(nextBranchId);
        setSelectedCategoryId("");
      } catch (fetchError) {
        if (isMounted) {
          setError(getErrorMessage(fetchError));
        }
      } finally {
        if (isMounted) {
          setIsLoadingBranches(false);
        }
      }
    }

    loadBranches();
    return () => {
      isMounted = false;
    };
  }, [canSelectAnyBranch, defaultBranchId]);

  useEffect(() => {
    if (branches.length === 0 || canSelectAnyBranch) {
      return;
    }

    const hasDefaultBranch = !!defaultBranchId && branches.some((branch) => branch.id === defaultBranchId);
    const forcedBranchId = hasDefaultBranch ? defaultBranchId : branches[0]?.id ?? "";
    if (forcedBranchId && forcedBranchId !== selectedBranchId) {
      setSelectedBranchId(forcedBranchId);
      setSelectedCategoryId("");
    }
  }, [branches, canSelectAnyBranch, defaultBranchId, selectedBranchId]);

  async function loadSummary() {
    if (!selectedBranchId || !startDate || !endDate) {
      return;
    }

    if (startDate > endDate) {
      setError("Start date must be before or equal to end date.");
      return;
    }

    setIsLoadingSummary(true);
    setError(null);

    try {
      const params: Record<string, string> = {
        branch_id: selectedBranchId,
        start_date: startDate,
        end_date: endDate
      };
      if (selectedCategoryId) {
        params.category_id = selectedCategoryId;
      }

      const response = await api.get<AnalyticsSummaryResponse>("/api/v1/analytics/summary", {
        params
      });

      setSummary({
        ...response.data,
        total_revenue: toNumber(response.data.total_revenue),
        total_expense: toNumber(response.data.total_expense),
        net_profit: toNumber(response.data.net_profit),
        expense_by_category: (response.data.expense_by_category || []).map((row) => ({
          ...row,
          total: toNumber(row.total)
        }))
      });

      if (typeof window !== "undefined" && canSelectAnyBranch) {
        window.localStorage.setItem("last_selected_branch_id", selectedBranchId);
      }
    } catch (fetchError) {
      setError(getErrorMessage(fetchError));
      setSummary(null);
    } finally {
      setIsLoadingSummary(false);
    }
  }

  useEffect(() => {
    if (!selectedBranchId) {
      return;
    }
    loadSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBranchId]);

  const selectedBranch = useMemo(
    () => branches.find((branch) => branch.id === selectedBranchId) || null,
    [branches, selectedBranchId]
  );

  const categoryOptions = useMemo(
    () => getCategoryOptions(selectedBranch?.type),
    [selectedBranch?.type]
  );

  const pieData = useMemo(
    () =>
      (summary?.expense_by_category || []).map((item) => ({
        name: item.category_id,
        value: item.total,
        label: `${item.category_id} (${item.category_name || "-"})`
      })),
    [summary?.expense_by_category]
  );

  const trendData = useMemo(
    () => [
      {
        period: "Selected Range",
        revenue: toNumber(summary?.total_revenue),
        expense: toNumber(summary?.total_expense)
      }
    ],
    [summary?.total_expense, summary?.total_revenue]
  );

  const currencyFormatter = useMemo(
    () =>
      new Intl.NumberFormat("th-TH", {
        style: "currency",
        currency: "THB",
        maximumFractionDigits: 0
      }),
    []
  );

  async function handleAskAi() {
    if (!question.trim()) {
      setAiError("Please enter a question.");
      return;
    }
    if (!selectedBranchId) {
      setAiError("Please select a store first.");
      return;
    }

    setIsAskingAi(true);
    setAiError(null);
    setAiAnswer("");
    setAiCitations([]);

    try {
      const response = await api.post<AiChatResponse>("/api/v1/ai/chat", {
        question: question.trim(),
        context_branch: selectedBranchId,
        start_date: startDate,
        end_date: endDate,
        category_id: selectedCategoryId || undefined
      });
      setAiAnswer(response.data.answer || "");
      setAiCitations(Array.isArray(response.data.citations) ? response.data.citations : []);
    } catch (askError) {
      setAiError(getErrorMessage(askError));
    } finally {
      setIsAskingAi(false);
    }
  }

  const netProfit = toNumber(summary?.net_profit);
  const netProfitClass =
    netProfit >= 0
      ? "border-blue-200 bg-blue-50 text-blue-700"
      : "border-red-200 bg-red-50 text-red-700";

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Executive Dashboard</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-5">
            <div className="space-y-1.5">
              <Label htmlFor="branch-select">Store</Label>
              {isLoadingBranches ? (
                <p className="flex h-10 items-center text-sm text-slate-600">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Loading stores...
                </p>
              ) : (
                <>
                  <select
                    id="branch-select"
                    className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    value={selectedBranchId}
                    onChange={(event) => {
                      setSelectedBranchId(event.target.value);
                      setSelectedCategoryId("");
                    }}
                    disabled={!canSelectAnyBranch}
                  >
                    {branches.map((branch) => (
                      <option key={branch.id} value={branch.id}>
                        {branch.name}
                      </option>
                    ))}
                  </select>
                  {!canSelectAnyBranch ? (
                    <p className="text-xs text-slate-500">
                      Staff role: store is fixed by your account permission.
                    </p>
                  ) : null}
                </>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="category-filter">Category</Label>
              <select
                id="category-filter"
                className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={selectedCategoryId}
                onChange={(event) => setSelectedCategoryId(event.target.value)}
                disabled={categoryOptions.length === 0}
              >
                <option value="">All Categories</option>
                {categoryOptions.map((categoryId) => (
                  <option key={categoryId} value={categoryId}>
                    {categoryId}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="start-date">Start Date</Label>
              <input
                id="start-date"
                type="date"
                className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="end-date">End Date</Label>
              <input
                id="end-date"
                type="date"
                className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </div>

            <div className="flex items-end">
              <Button
                type="button"
                className="w-full"
                onClick={loadSummary}
                disabled={isLoadingSummary || !selectedBranchId || !startDate || !endDate}
              >
                {isLoadingSummary ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Loading...
                  </>
                ) : (
                  "Apply Filters"
                )}
              </Button>
            </div>
          </div>

          {error ? (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-green-200 bg-green-50">
          <CardHeader>
            <CardTitle className="text-sm text-green-700">Total Revenue</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold text-green-800">
              {currencyFormatter.format(toNumber(summary?.total_revenue))}
            </p>
          </CardContent>
        </Card>

        <Card className="border-red-200 bg-red-50">
          <CardHeader>
            <CardTitle className="text-sm text-red-700">Total Expense</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold text-red-800">
              {currencyFormatter.format(toNumber(summary?.total_expense))}
            </p>
          </CardContent>
        </Card>

        <Card className={netProfitClass}>
          <CardHeader>
            <CardTitle className="text-sm">Net Profit</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold">{currencyFormatter.format(netProfit)}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Expense Composition</CardTitle>
          </CardHeader>
          <CardContent className="h-[320px]">
            {pieData.length === 0 ? (
              <p className="text-sm text-slate-500">No expense data in selected range.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={100} label>
                    {pieData.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value: number, _, payload) => [
                      currencyFormatter.format(toNumber(value)),
                      payload?.payload?.label || "Category"
                    ]}
                  />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Daily Trend (Summary)</CardTitle>
          </CardHeader>
          <CardContent className="h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={trendData}>
                <XAxis dataKey="period" />
                <YAxis />
                <Tooltip formatter={(value: number) => currencyFormatter.format(toNumber(value))} />
                <Legend />
                <Bar dataKey="revenue" name="Revenue" fill="#16a34a" />
                <Bar dataKey="expense" name="Expense" fill="#dc2626" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            AI Insight
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="ai-question">Ask about this branch performance</Label>
          <textarea
            id="ai-question"
            className="min-h-28 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
            placeholder="Example: Why did net profit drop this month?"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />

          <Button type="button" onClick={handleAskAi} disabled={isAskingAi || !question.trim()}>
            {isAskingAi ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Asking AI...
              </>
            ) : (
              "Ask AI"
            )}
          </Button>

          {aiError ? (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {aiError}
            </p>
          ) : null}

          {aiAnswer ? (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
              <p className="whitespace-pre-line">{aiAnswer}</p>
              {aiCitations.length > 0 ? (
                <div className="mt-3 border-t border-slate-200 pt-2">
                  <p className="text-xs font-semibold text-slate-600">Citations</p>
                  <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-slate-600">
                    {aiCitations.map((citation) => (
                      <li key={citation}>{citation}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
