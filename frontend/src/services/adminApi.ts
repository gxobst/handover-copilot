import { apiClient, type RequestConfig } from './apiClient.ts';
import type {
  AdminSettingsResponse,
  AdminSettingsUpdate,
} from '../types/api.ts';
import type { AdminService } from './types.ts';

export const adminApi: AdminService = {
  /**
   * Retrieves active and fallback model routing configurations.
   * Requires Bearer token authentication.
   * GET /api/admin/settings
   */
  getSettings(token?: string, config?: RequestConfig): Promise<AdminSettingsResponse> {
    return apiClient.get<AdminSettingsResponse>('/admin/settings', {
      ...config,
      ...(token ? { token } : {}),
    });
  },

  /**
   * Dynamically reconfigures active and/or fallback models at runtime.
   * Requires Bearer token authentication.
   * PUT /api/admin/settings
   */
  updateSettings(
    payload: AdminSettingsUpdate,
    token?: string,
    config?: RequestConfig
  ): Promise<AdminSettingsResponse> {
    return apiClient.put<AdminSettingsResponse, AdminSettingsUpdate>('/admin/settings', payload, {
      ...config,
      ...(token ? { token } : {}),
    });
  },
};

export const realAdminApi = adminApi;
export default adminApi;
