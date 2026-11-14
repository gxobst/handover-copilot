import { apiClient, type RequestConfig } from './apiClient.ts';
import type {
  ReportGenerateRequest,
  ReportResponse,
  ReportSummary,
  ShiftKey,
} from '../types/api.ts';

export const reportsApi = {
  /**
   * Invokes Gemini LLM with structured outputs to generate a shift handover report.
   * POST /api/reports/generate
   */
  generateReport(payload: ReportGenerateRequest, config?: RequestConfig): Promise<ReportResponse> {
    return apiClient.post<ReportResponse, ReportGenerateRequest>('/reports/generate', payload, config);
  },

  /**
   * Retrieves historical report summaries, optionally filtered by shift key.
   * GET /api/reports
   */
  listReports(shiftKey?: ShiftKey | string, config?: RequestConfig): Promise<ReportSummary[]> {
    return apiClient.get<ReportSummary[]>('/reports', {
      ...config,
      params: {
        ...config?.params,
        ...(shiftKey ? { shiftKey } : {}),
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

export default reportsApi;
