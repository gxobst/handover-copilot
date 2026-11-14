import { apiClient, type RequestConfig } from './apiClient.ts';
import type {
  ReportGenerateRequest,
  ReportResponse,
  ReportSummary,
  ShiftKey,
} from '../types/api.ts';
import type { ReportsService } from './types.ts';

export const reportsApi: ReportsService = {
  /**
   * Invokes Gemini LLM with structured outputs to generate a shift handover report.
   * POST /api/reports/generate
   */
  generateReport(payload: ReportGenerateRequest, config?: RequestConfig): Promise<ReportResponse> {
    return apiClient.post<ReportResponse, ReportGenerateRequest>('/reports/generate', payload, config);
  },

  /**
   * Retrieves historical report summaries, optionally filtered by shift key and capped at limit.
   * GET /api/reports
   */
  listReports(
    shiftKey?: ShiftKey | string,
    limitOrConfig?: number | RequestConfig,
    config?: RequestConfig
  ): Promise<ReportSummary[]> {
    const limit = typeof limitOrConfig === 'number' ? limitOrConfig : undefined;
    const actualConfig = typeof limitOrConfig === 'object' ? limitOrConfig : config;

    return apiClient.get<ReportSummary[]>('/reports', {
      ...actualConfig,
      params: {
        ...actualConfig?.params,
        ...(shiftKey ? { shiftKey } : {}),
        ...(limit !== undefined ? { limit } : {}),
      },
    });
  },

  /**
   * Retrieves the complete immutable snapshot of a handover report by ID.
   * GET /api/reports/{id}
   */
  getReport(id: string, config?: RequestConfig): Promise<ReportResponse> {
    return apiClient.get<ReportResponse>(`/reports/${encodeURIComponent(id)}`, config);
  },
};

export const realReportsApi = reportsApi;
export default reportsApi;
