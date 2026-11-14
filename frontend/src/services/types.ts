import type { RequestConfig } from './apiClient.ts';
import type {
  HealthResponse,
  EventResponse,
  EventCreateRequest,
  ShiftKey,
  ReportResponse,
  ReportSummary,
  ReportGenerateRequest,
  AdminSettingsResponse,
  AdminSettingsUpdate,
} from '../types/api.ts';

/**
 * Common TypeScript service contract for Health operations.
 */
export interface HealthService {
  /**
   * Performs service operational health check.
   * GET /api/healthz
   */
  getHealth(config?: RequestConfig): Promise<HealthResponse>;
}

/**
 * Common TypeScript service contract for Shift Event operations.
 */
export interface EventsService {
  /**
   * Records a new operational shift event.
   * POST /api/events
   */
  createEvent(payload: EventCreateRequest, config?: RequestConfig): Promise<EventResponse>;

  /**
   * Retrieves all logged events for a given shift key, sorted chronologically ascending.
   * GET /api/events?shiftKey=...
   */
  listEvents(shiftKey: ShiftKey | string, config?: RequestConfig): Promise<EventResponse[]>;

  /**
   * Permanently deletes an event by its unique UUID.
   * DELETE /api/events/{id}
   */
  deleteEvent(id: string, config?: RequestConfig): Promise<void>;
}

/**
 * Common TypeScript service contract for Shift Handover Report operations.
 */
export interface ReportsService {
  /**
   * Synthesizes or retrieves a shift handover report.
   * POST /api/reports/generate
   */
  generateReport(payload: ReportGenerateRequest, config?: RequestConfig): Promise<ReportResponse>;

  /**
   * Retrieves historical report summaries, optionally filtered by shift key and capped at limit.
   * GET /api/reports
   */
  listReports(
    shiftKey?: ShiftKey | string,
    limitOrConfig?: number | RequestConfig,
    config?: RequestConfig
  ): Promise<ReportSummary[]>;

  /**
   * Retrieves the complete immutable snapshot of a handover report by ID.
   * GET /api/reports/{id}
   */
  getReport(id: string, config?: RequestConfig): Promise<ReportResponse>;
}

/**
 * Common TypeScript service contract for Administrative Settings operations.
 */
export interface AdminService {
  /**
   * Retrieves active and fallback model routing configurations.
   * GET /api/admin/settings
   */
  getSettings(token?: string, config?: RequestConfig): Promise<AdminSettingsResponse>;

  /**
   * Dynamically reconfigures active and/or fallback models at runtime.
   * PUT /api/admin/settings
   */
  updateSettings(
    payload: AdminSettingsUpdate,
    token?: string,
    config?: RequestConfig
  ): Promise<AdminSettingsResponse>;
}
