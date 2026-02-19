"use client";

import { useEffect, useRef, useState } from "react";
import { FileSpreadsheet, Loader2, UploadCloud } from "lucide-react";

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

type PosUploadResponse = {
  status: string;
  branch_id: string;
  rows_inserted: number;
};

function getErrorMessage(error: unknown): string {
  if (
    typeof error === "object" &&
    error &&
    "response" in error &&
    typeof (error as { response?: { data?: { detail?: unknown } } }).response === "object"
  ) {
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }
  return "POS import failed. Please try again.";
}

export default function PosImportPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [branches, setBranches] = useState<Branch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isLoadingBranches, setIsLoadingBranches] = useState(true);
  const [branchError, setBranchError] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadBranches() {
      setIsLoadingBranches(true);
      setBranchError(null);

      try {
        const response = await api.get<BranchListResponse>("/api/v1/branches");
        if (!isMounted) {
          return;
        }
        const branchList = response.data.branches || [];
        setBranches(branchList);
        setSelectedBranchId(branchList[0]?.id ?? "");
      } catch (fetchError) {
        if (!isMounted) {
          return;
        }
        setBranchError(getErrorMessage(fetchError));
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
  }, []);

  function handleFileChange(file: File | null) {
    setError(null);
    setSuccessMessage(null);
    setSelectedFile(file);
  }

  async function handleImport() {
    if (!selectedBranchId) {
      setError("Please select a branch.");
      return;
    }
    if (!selectedFile) {
      setError("Please select a CSV or Excel file.");
      return;
    }

    setError(null);
    setSuccessMessage(null);
    setIsImporting(true);

    try {
      const formData = new FormData();
      formData.append("branch_id", selectedBranchId);
      formData.append("file", selectedFile);

      const response = await api.post<PosUploadResponse>("/api/v1/pos/upload", formData, {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      });

      setSuccessMessage(
        `Import completed for ${response.data.branch_id}. ${response.data.rows_inserted} rows inserted.`
      );
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (importError) {
      setError(getErrorMessage(importError));
    } finally {
      setIsImporting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileSpreadsheet className="h-5 w-5" />
          POS Import
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <Label htmlFor="pos-branch">Store</Label>
          {isLoadingBranches ? (
            <p className="flex h-10 items-center text-sm text-slate-600">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading stores...
            </p>
          ) : branchError ? (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {branchError}
            </p>
          ) : branches.length === 0 ? (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
              No stores found. Please configure branches first.
            </p>
          ) : (
            <select
              id="pos-branch"
              className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={selectedBranchId}
              onChange={(event) => setSelectedBranchId(event.target.value)}
              disabled={isImporting}
            >
              {branches.map((branch) => (
                <option key={branch.id} value={branch.id}>
                  {branch.name} ({branch.type})
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="pos-file">POS File (CSV / XLS / XLSX)</Label>
          <input
            ref={fileInputRef}
            id="pos-file"
            type="file"
            accept=".csv,.xls,.xlsx"
            className="block w-full cursor-pointer rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 file:mr-4 file:cursor-pointer file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
            onChange={(event) => handleFileChange(event.target.files?.[0] ?? null)}
            disabled={isImporting}
          />
          {selectedFile ? (
            <p className="text-xs text-slate-500">Selected: {selectedFile.name}</p>
          ) : null}
        </div>

        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          Required columns: <span className="font-medium">date</span>,{" "}
          <span className="font-medium">amount</span>,{" "}
          <span className="font-medium">payment_method</span>. Alias columns are supported by backend
          normalization.
        </div>

        {error ? (
          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        ) : null}

        {successMessage ? (
          <p className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            {successMessage}
          </p>
        ) : null}

        <Button
          type="button"
          onClick={handleImport}
          disabled={isImporting || !selectedBranchId || !selectedFile || branches.length === 0}
        >
          {isImporting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Importing...
            </>
          ) : (
            <>
              <UploadCloud className="mr-2 h-4 w-4" />
              Import POS File
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
