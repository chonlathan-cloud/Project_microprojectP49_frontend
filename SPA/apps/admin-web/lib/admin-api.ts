/* eslint-disable @typescript-eslint/no-explicit-any */
import type { User } from "firebase/auth";

type UnknownPayload = unknown;

type ApiResponse<T> = {
  payload: T;
  response: Response;
};

async function requestAdminResponse(
  user: User,
  path: string,
  init: RequestInit = {},
  forceRefresh = false,
): Promise<ApiResponse<UnknownPayload>> {
  const token = await user.getIdToken(forceRefresh);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`/api/spa/api/v1/admin${path}`, {
    ...init,
    cache: "no-store",
    headers,
  });
  const payload = response.status === 204 ? null : await response.json().catch(() => null);

  if (response.status === 401 && !forceRefresh) {
    return requestAdminResponse(user, path, init, true);
  }

  return { response, payload };
}

export async function adminApi<T>(user: User, path: string, init: RequestInit = {}): Promise<T> {
  const { response, payload } = await requestAdminResponse(user, path, init, false);
  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in (payload as Record<string, any>)
        ? String((payload as Record<string, any>).detail)
        : "Admin API request failed";
    throw new Error(detail);
  }
  return payload as T;
}

async function requestAdminDownload(user: User, path: string, init: RequestInit, forceRefresh: boolean): Promise<Response> {
  const token = await user.getIdToken(forceRefresh);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/spa/api/v1/admin${path}`, { ...init, cache: "no-store", headers });
  if (response.status === 401 && !forceRefresh) return requestAdminDownload(user, path, init, true);
  return response;
}

export async function adminDownload(user: User, path: string, init: RequestInit = {}): Promise<void> {
  const response = await requestAdminDownload(user, path, init, false);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? "Admin export failed");
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? "spa49-export.csv";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
