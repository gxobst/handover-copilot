import { apiClient, type RequestConfig } from './apiClient.ts';
import type { HealthResponse } from '../types/api.ts';

export const healthApi = {
  /**
   * Performs service operational health check.
   * GET /api/healthz
   */
  getHealth(config?: RequestConfig): Promise<HealthResponse> {
    return apiClient.get<HealthResponse>('/healthz', config);
  },
};

export default healthApi;
