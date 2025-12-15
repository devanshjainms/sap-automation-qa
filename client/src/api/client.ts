// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * API Client - Axios instance with interceptors.
 */
import axios, {
  AxiosInstance,
  AxiosError,
  InternalAxiosRequestConfig,
} from "axios";
import { APP_CONFIG } from "../constants";

// Fallback for crypto.randomUUID (not available in non-HTTPS contexts)
export const generateUUID = (): string => {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // Fallback implementation
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
};

const createApiClient = (): AxiosInstance => {
  const client = axios.create({
    baseURL: APP_CONFIG.API_BASE_URL,
    timeout: APP_CONFIG.API_TIMEOUT,
    headers: {
      "Content-Type": "application/json",
    },
  });

  client.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
      const correlationId = generateUUID();
      config.headers.set("X-Correlation-ID", correlationId);
      return config;
    },
    (error: AxiosError) => {
      return Promise.reject(error);
    },
  );

  client.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
      const originalRequest = error.config as InternalAxiosRequestConfig & {
        _retry?: boolean;
      };

      const correlationId = originalRequest?.headers?.get?.("X-Correlation-ID") || "unknown";
      
      if (error.response?.status === 401) {
        console.error(`[${correlationId}] Authentication required`);
      }

      if (error.response?.status === 503 && !originalRequest._retry) {
        console.warn(`[${correlationId}] Service unavailable, retrying...`);
        originalRequest._retry = true;
        await new Promise((resolve) =>
          setTimeout(resolve, APP_CONFIG.API_RETRY_DELAY),
        );
        return client(originalRequest);
      }

      console.error(`[${correlationId}] API error:`, error.response?.status, error.message);
      return Promise.reject(error);
    },
  );

  return client;
};

export const apiClient = createApiClient();
