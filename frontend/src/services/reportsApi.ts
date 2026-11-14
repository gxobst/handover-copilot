import { apiClient, type RequestConfig } from './apiClient.ts';
import type {
  ReportGenerateRequest,
  ReportResponse,
  ReportSummary,
  ShiftKey,
} from '../types/api.ts';
import type { ReportsService } from './types.ts';

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
 * Normalizes a handover report response object ensuring both camelCase and snake_case properties are present.
 */
export function normalizeReportResponse(data: unknown): ReportResponse {
  if (!data || typeof data !== 'object') {
    return data as ReportResponse;
  }
  const raw = data as Record<string, unknown>;
  const shiftKey = (raw.shiftKey ?? raw.shift_key ?? '') as ShiftKey;
  const modelUsed = (raw.modelUsed ?? raw.model_used ?? '') as string;
  const eventCount = (raw.eventCount ?? raw.event_count ?? 0) as number;
  const createdAt = (raw.createdAt ?? raw.created_at ?? '') as string;
  const openActions = (raw.openActions ?? raw.open_actions ?? []) as ReportResponse['openActions'];
  const safetyNotes = (raw.safetyNotes ?? raw.safety_notes ?? []) as string[];

  const result: ReportResponse = {
    ...(raw as unknown as ReportResponse),
    shiftKey,
    modelUsed,
    eventCount,
    createdAt,
    openActions,
    safetyNotes,
  };

  ensureProperty(result, 'shift_key', raw.shift_key ?? shiftKey, 'shift_key' in raw);
  ensureProperty(result, 'model_used', raw.model_used ?? modelUsed, 'model_used' in raw);
  ensureProperty(result, 'event_count', raw.event_count ?? eventCount, 'event_count' in raw);
  ensureProperty(result, 'created_at', raw.created_at ?? createdAt, 'created_at' in raw);
  ensureProperty(result, 'open_actions', raw.open_actions ?? openActions, 'open_actions' in raw);
  ensureProperty(result, 'safety_notes', raw.safety_notes ?? safetyNotes, 'safety_notes' in raw);

  return result;
}

/**
 * Normalizes a report summary object ensuring both camelCase and snake_case properties are present.
 */
export function normalizeReportSummary(data: unknown): ReportSummary {
  if (!data || typeof data !== 'object') {
    return data as ReportSummary;
  }
  const raw = data as Record<string, unknown>;
  const shiftKey = (raw.shiftKey ?? raw.shift_key ?? '') as ShiftKey;
  const modelUsed = (raw.modelUsed ?? raw.model_used ?? '') as string;
  const eventCount = (raw.eventCount ?? raw.event_count ?? 0) as number;
  const createdAt = (raw.createdAt ?? raw.created_at ?? '') as string;

  const result: ReportSummary = {
    ...(raw as unknown as ReportSummary),
    shiftKey,
    modelUsed,
    eventCount,
    createdAt,
  };

  ensureProperty(result, 'shift_key', raw.shift_key ?? shiftKey, 'shift_key' in raw);
  ensureProperty(result, 'model_used', raw.model_used ?? modelUsed, 'model_used' in raw);
  ensureProperty(result, 'event_count', raw.event_count ?? eventCount, 'event_count' in raw);
  ensureProperty(result, 'created_at', raw.created_at ?? createdAt, 'created_at' in raw);

  return result;
}

export const reportsApi: ReportsService = {
  /**
   * Invokes Gemini LLM with structured outputs to generate a shift handover report.
   * POST /api/reports/generate
   */
  async generateReport(payload: ReportGenerateRequest, config?: RequestConfig): Promise<ReportResponse> {
    const raw = await apiClient.post<ReportResponse, ReportGenerateRequest>('/reports/generate', payload, config);
    return normalizeReportResponse(raw);
  },

  /**
   * Retrieves historical report summaries, optionally filtered by shift key and capped at limit.
   * GET /api/reports
   */
  async listReports(
    shiftKey?: ShiftKey | string,
    limitOrConfig?: number | RequestConfig,
    config?: RequestConfig
  ): Promise<ReportSummary[]> {
    const limit = typeof limitOrConfig === 'number' ? limitOrConfig : undefined;
    const actualConfig = typeof limitOrConfig === 'object' ? limitOrConfig : config;

    const rawList = await apiClient.get<ReportSummary[]>('/reports', {
      ...actualConfig,
      params: {
        ...actualConfig?.params,
        ...(shiftKey ? { shiftKey } : {}),
        ...(limit !== undefined ? { limit } : {}),
      },
    });
    return Array.isArray(rawList) ? rawList.map(normalizeReportSummary) : [];
  },

  /**
   * Retrieves the complete immutable snapshot of a handover report by ID.
   * GET /api/reports/{id}
   */
  async getReport(id: string, config?: RequestConfig): Promise<ReportResponse> {
    const raw = await apiClient.get<ReportResponse>(`/reports/${encodeURIComponent(id)}`, config);
    return normalizeReportResponse(raw);
  },
};

export const realReportsApi = reportsApi;
export default reportsApi;
