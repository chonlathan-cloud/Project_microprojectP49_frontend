import axios, { AxiosHeaders, type InternalAxiosRequestConfig } from "axios";

import { auth } from "@/lib/firebase";

const baseURL =
  process.env.NEXT_PUBLIC_BACKEND_URL?.trim() || "http://localhost:8000";

const api = axios.create({
  baseURL,
  timeout: 30000
});

api.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const user = auth.currentUser;
    if (!user) {
      return config;
    }

    const token = await user.getIdToken();
    const headers = AxiosHeaders.from(config.headers);
    headers.set("Authorization", `Bearer ${token}`);
    config.headers = headers;
    return config;
  },
  (error) => Promise.reject(error)
);

export default api;
