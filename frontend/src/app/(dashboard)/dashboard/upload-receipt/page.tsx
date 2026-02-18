"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileUp, Loader2, UploadCloud } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import api from "@/lib/api";

type UploadResponse = {
  receipt_id: string;
  status: string;
};

type Branch = {
  id: string;
  name: string;
  type: "COFFEE" | "RESTAURANT";
};

type BranchListResponse = {
  branches: Branch[];
};

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
  return "Upload failed. Please try again.";
}

export default function UploadReceiptPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [branches, setBranches] = useState<Branch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState("");
  const [isLoadingBranches, setIsLoadingBranches] = useState(true);
  const [branchError, setBranchError] = useState<string | null>(null);
  const [branchFetchNonce, setBranchFetchNonce] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

        const lastSelectedId =
          typeof window !== "undefined"
            ? window.localStorage.getItem("last_selected_branch_id")
            : null;
        const hasLastSelected = !!lastSelectedId && branchList.some((b) => b.id === lastSelectedId);

        setSelectedBranchId(
          hasLastSelected ? (lastSelectedId as string) : (branchList[0]?.id ?? "")
        );
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
  }, [branchFetchNonce]);

  function openFilePicker() {
    fileInputRef.current?.click();
  }

  function onFileSelected(file: File | null) {
    setError(null);
    setSelectedFile(file);
  }

  async function handleUpload() {
    if (!selectedFile) {
      setError("Please select a receipt file first.");
      return;
    }

    if (!selectedBranchId) {
      setError("Please select a store before uploading.");
      return;
    }

    setIsUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("branch_id", selectedBranchId);
      formData.append("file", selectedFile);

      const response = await api.post<UploadResponse>("/api/v1/receipts/upload", formData, {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      });
      if (typeof window !== "undefined") {
        window.localStorage.setItem("last_selected_branch_id", selectedBranchId);
      }

      router.push(`/dashboard/receipts/${response.data.receipt_id}`);
    } catch (uploadError) {
      setError(getErrorMessage(uploadError));
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileUp className="h-5 w-5" />
            Upload Receipt
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="branch-select">Store</Label>
            {isLoadingBranches ? (
              <p className="flex h-10 items-center text-sm text-slate-600">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Loading stores...
              </p>
            ) : branchError ? (
              <div className="space-y-2">
                <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {branchError}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setBranchFetchNonce((prev) => prev + 1)}
                >
                  Retry
                </Button>
              </div>
            ) : branches.length === 0 ? (
              <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                No stores found. Please configure branches first.
              </p>
            ) : (
              <select
                id="branch-select"
                className="flex h-10 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={selectedBranchId}
                onChange={(event) => setSelectedBranchId(event.target.value)}
                disabled={isUploading}
              >
                {branches.map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name} ({branch.type})
                  </option>
                ))}
              </select>
            )}
            <p className="text-xs text-slate-500">
              Policy: 1 receipt is linked to exactly 1 store.
            </p>
          </div>

          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,.pdf"
              className="hidden"
              onChange={(event) => onFileSelected(event.target.files?.[0] ?? null)}
              disabled={isUploading}
            />

            <button
              type="button"
              className={`flex w-full flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
                isDragging
                  ? "border-slate-700 bg-slate-100"
                  : "border-slate-300 bg-slate-50 hover:border-slate-500"
              }`}
              onClick={openFilePicker}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragging(false);
                onFileSelected(event.dataTransfer.files?.[0] ?? null);
              }}
              disabled={isUploading}
            >
              <UploadCloud className="h-8 w-8 text-slate-500" />
              <p className="mt-3 font-medium text-slate-800">Drag and drop a receipt file here</p>
              <p className="mt-1 text-sm text-slate-500">or click to browse</p>
              {selectedFile ? (
                <p className="mt-3 rounded-md bg-slate-200 px-3 py-1 text-sm text-slate-700">
                  Selected: {selectedFile.name}
                </p>
              ) : null}
            </button>
          </div>

          {error ? (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          ) : null}

          <Button
            type="button"
            onClick={handleUpload}
            disabled={isUploading || !selectedFile || !selectedBranchId || branches.length === 0}
            className="w-full sm:w-auto"
          >
            {isUploading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Processing OCR...
              </>
            ) : (
              "Upload and Process"
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
