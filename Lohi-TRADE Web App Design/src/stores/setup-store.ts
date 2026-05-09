/**
 * Setup Wizard Zustand store.
 *
 * Manages the state for the Easy Setup Wizard — service statuses,
 * current step, loading/error states, and API interactions with the
 * backend setup endpoints.
 *
 * Requirements: 3.4, 3.5
 * Design: §Components and Interfaces → Frontend Components → setup-store.ts
 */

import { create } from 'zustand';
import axios from 'axios';
import { ApiClientError } from '../lib/api-client';
import type { ServiceStatus, TestResult, SetupStatusResponse } from '../lib/setup-types';

// ─── State & Actions ────────────────────────────────────────────────────────

export interface SetupState {
  /** Current status of all credential groups. */
  services: ServiceStatus[];
  /** Active wizard step index (0-based). */
  currentStep: number;
  /** Whether the user has completed the initial setup flow. */
  setupComplete: boolean;
  /** Global loading indicator for async operations. */
  loading: boolean;
  /** Last error message from a failed operation. */
  error: string | null;
}

export interface SetupActions {
  /** Fetch current setup status from the backend. */
  fetchStatus: () => Promise<void>;
  /** Submit credentials for a credential group. */
  submitCredentials: (groupId: string, credentials: Record<string, string>) => Promise<void>;
  /** Test the connection for a credential group. Returns the test result. */
  testConnection: (groupId: string) => Promise<TestResult>;
  /** Mark a credential group as skipped. */
  skipGroup: (groupId: string) => Promise<void>;
  /** Reset a credential group to unconfigured. */
  resetGroup: (groupId: string) => Promise<void>;
  /** Finalize the setup wizard. */
  completeSetup: () => Promise<void>;
}

export type SetupStore = SetupState & SetupActions;

// ─── API Base URL ───────────────────────────────────────────────────────────

const BASE_URL: string =
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ((import.meta as any).env?.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

// Setup endpoints don't require auth (localhost-only guard on backend).
// We use a plain axios instance without the JWT interceptor.
const setupHttp = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

// ─── Helpers ────────────────────────────────────────────────────────────────

function extractErrorMessage(err: unknown): string {
  if (err instanceof ApiClientError) {
    return err.detail ?? err.message;
  }
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (err.code === 'ECONNABORTED') return 'Request timed out';
    if (!err.response) return 'Network error — unable to reach the server';
    return `HTTP ${err.response.status}: ${err.message}`;
  }
  if (err instanceof Error) return err.message;
  return 'An unexpected error occurred';
}

// ─── Store ──────────────────────────────────────────────────────────────────

export const useSetupStore = create<SetupStore>((set, get) => ({
  services: [],
  currentStep: 0,
  setupComplete: false,
  loading: false,
  error: null,

  fetchStatus: async () => {
    set({ loading: true, error: null });
    try {
      const { data } = await setupHttp.get<SetupStatusResponse>('/api/setup/status');
      set({
        services: data.services,
        setupComplete: data.setup_complete,
        loading: false,
      });
    } catch (err) {
      set({ error: extractErrorMessage(err), loading: false });
    }
  },

  submitCredentials: async (groupId, credentials) => {
    set({ loading: true, error: null });
    try {
      await setupHttp.post(`/api/setup/credentials/${groupId}`, { credentials });
      // Refresh status to reflect the new state
      await get().fetchStatus();
    } catch (err) {
      set({ error: extractErrorMessage(err), loading: false });
      throw err;
    }
  },

  testConnection: async (groupId) => {
    set({ loading: true, error: null });
    try {
      const { data } = await setupHttp.post<TestResult>(`/api/setup/test/${groupId}`);
      set({ loading: false });
      return data;
    } catch (err) {
      set({ error: extractErrorMessage(err), loading: false });
      throw err;
    }
  },

  skipGroup: async (groupId) => {
    set({ loading: true, error: null });
    try {
      await setupHttp.post(`/api/setup/skip/${groupId}`);
      // Refresh status to reflect the skip
      await get().fetchStatus();
    } catch (err) {
      set({ error: extractErrorMessage(err), loading: false });
      throw err;
    }
  },

  resetGroup: async (groupId) => {
    set({ loading: true, error: null });
    try {
      await setupHttp.post(`/api/setup/reset/${groupId}`);
      // Refresh status to reflect the reset
      await get().fetchStatus();
    } catch (err) {
      set({ error: extractErrorMessage(err), loading: false });
      throw err;
    }
  },

  completeSetup: async () => {
    set({ loading: true, error: null });
    try {
      await setupHttp.post('/api/setup/complete');
      set({ setupComplete: true, loading: false });
    } catch (err) {
      set({ error: extractErrorMessage(err), loading: false });
      throw err;
    }
  },
}));
