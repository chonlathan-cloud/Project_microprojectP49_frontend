import axios, { AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import type { User } from "firebase/auth";

import { auth } from "@/lib/firebase";

const TOKEN_TIMEOUT_MS = 10000;

const baseURL =
  process.env.NEXT_PUBLIC_BACKEND_URL?.trim() || "http://localhost:8000";

const api = axios.create({
  baseURL,
  timeout: 30000
});

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const timeoutPromise = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(message)), timeoutMs);
  });

  return Promise.race([promise, timeoutPromise]).finally(() => {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
  });
}

function getIdTokenWithTimeout(user: User): Promise<string> {
  return withTimeout(
    user.getIdToken(),
    TOKEN_TIMEOUT_MS,
    "Timed out while reading authentication token."
  );
}

api.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const requestUrl = String(config.url || "");
    if (requestUrl === "/api/v1/branches" || requestUrl.startsWith("/api/v1/branches?")) {
      return config;
    }

    const user = auth.currentUser;
    if (!user) {
      return config;
    }

    const token = await getIdTokenWithTimeout(user);
    const headers = AxiosHeaders.from(config.headers);
    headers.set("Authorization", `Bearer ${token}`);
    config.headers = headers;
    return config;
  },
  (error) => Promise.reject(error)
);

export default api;
