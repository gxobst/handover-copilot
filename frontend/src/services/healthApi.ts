import { apiClient, type RequestConfig } from './apiClient.ts';
import type { HealthResponse } from '../types/api.ts';
import type { HealthService } from './types.ts';

export const healthApi: HealthService = {
  /**
   * Performs service operational health check.
   * GET /api/healthz
   */
  getHealth(config?: RequestConfig): Promise<HealthResponse> {
    return apiClient.get<HealthResponse>('/healthz', config);
  },
};

export const realHealthApi = healthApi;
export default healthApi;
