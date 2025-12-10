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
      const correlationId = crypto.randomUUID();
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

      if (error.response?.status === 401) {
        console.error("Authentication required");
      }

      if (error.response?.status === 503 && !originalRequest._retry) {
        originalRequest._retry = true;
        await new Promise((resolve) =>
          setTimeout(resolve, APP_CONFIG.API_RETRY_DELAY),
        );
        return client(originalRequest);
      }

      return Promise.reject(error);
    },
  );

  return client;
};

export const apiClient = createApiClient();
