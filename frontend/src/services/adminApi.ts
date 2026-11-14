import { apiClient, type RequestConfig } from './apiClient.ts';
import type {
  AdminSettingsResponse,
  AdminSettingsUpdate,
} from '../types/api.ts';
import type { AdminService } from './types.ts';

function ensureProperty<T extends object>(
  obj: T,
  prop: string,
  val: unknown,
  keepEnumerable: boolean
): void {
  if (keepEnumerable) {
    (obj as Record<string, unknown>)[prop] = val;
  } else {
    Object.defineProperty(obj, prop, {
      value: val,
      enumerable: false,
      configurable: true,
      writable: true,
    });
  }
}

/**
 * Normalizes an admin settings response ensuring both camelCase and snake_case properties are present.
 */
export function normalizeAdminSettings(data: unknown): AdminSettingsResponse {
  if (!data || typeof data !== 'object') {
    return data as AdminSettingsResponse;
  }
  const raw = data as Record<string, unknown>;
  const activeModel = (raw.activeModel ?? raw.active_model ?? '') as string;
  const fallbackModel = (raw.fallbackModel ?? raw.fallback_model ?? '') as string;

  const result: AdminSettingsResponse = {
    ...(raw as unknown as AdminSettingsResponse),
    activeModel,
    fallbackModel,
  };

  ensureProperty(result, 'active_model', raw.active_model ?? activeModel, 'active_model' in raw);
  ensureProperty(result, 'fallback_model', raw.fallback_model ?? fallbackModel, 'fallback_model' in raw);

  return result;
}

export const adminApi: AdminService = {
  /**
   * Retrieves active and fallback model routing configurations.
   * Requires Bearer token authentication.
   * GET /api/admin/settings
   */
  async getSettings(token?: string, config?: RequestConfig): Promise<AdminSettingsResponse> {
    const raw = await apiClient.get<AdminSettingsResponse>('/admin/settings', {
      ...config,
      ...(token ? { token } : {}),
    });
    return normalizeAdminSettings(raw);
  },

  /**
   * Dynamically reconfigures active and/or fallback models at runtime.
   * Requires Bearer token authentication.
   * PUT /api/admin/settings
   */
  async updateSettings(
    payload: AdminSettingsUpdate,
    token?: string,
    config?: RequestConfig
  ): Promise<AdminSettingsResponse> {
    const raw = await apiClient.put<AdminSettingsResponse, AdminSettingsUpdate>('/admin/settings', payload, {
      ...config,
      ...(token ? { token } : {}),
    });
    return normalizeAdminSettings(raw);
  },
};

export const realAdminApi = adminApi;
export default adminApi;
