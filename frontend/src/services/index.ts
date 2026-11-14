import type {
  HealthService,
  EventsService,
  ReportsService,
  AdminService,
} from './types.ts';
import { realHealthApi } from './healthApi.ts';
import { realEventsApi } from './eventsApi.ts';
import { realReportsApi } from './reportsApi.ts';
import { realAdminApi } from './adminApi.ts';
import {
  mockHealthApi,
  mockEventsApi,
  mockReportsApi,
  mockAdminApi,
} from './mockServices.ts';

export * from './types.ts';
export * from './errors.ts';
export * from './apiClient.ts';
export { realHealthApi } from './healthApi.ts';
export { realEventsApi } from './eventsApi.ts';
export { realReportsApi } from './reportsApi.ts';
export { realAdminApi } from './adminApi.ts';
export * from './mockServices.ts';

let apiModeOverride: 'mock' | 'real' | null = null;

/**
 * Programmatically overrides API mode routing between mock and real.
 * Passing `null` restores dynamic detection via `import.meta.env.VITE_API_MODE`.
 */
export function setApiModeOverride(mode: 'mock' | 'real' | null): void {
  apiModeOverride = mode;
}

/**
 * Determines whether services route to in-memory mocks or the live backend API.
 * Returns true if VITE_API_MODE === 'mock' (or overridden to 'mock').
 */
export function isMockMode(): boolean {
  if (apiModeOverride !== null) {
    return apiModeOverride === 'mock';
  }
  const envMode =
    typeof import.meta !== 'undefined' && import.meta.env
      ? import.meta.env.VITE_API_MODE
      : undefined;
  return envMode === 'mock';
}

/**
 * Unified Health API service instance routing to mock or real client based on VITE_API_MODE.
 */
export const healthApi: HealthService = {
  getHealth: (config) =>
    isMockMode() ? mockHealthApi.getHealth(config) : realHealthApi.getHealth(config),
};

/**
 * Unified Events API service instance routing to mock or real client based on VITE_API_MODE.
 */
export const eventsApi: EventsService = {
  createEvent: (payload, config) =>
    isMockMode()
      ? mockEventsApi.createEvent(payload, config)
      : realEventsApi.createEvent(payload, config),
  listEvents: (shiftKey, config) =>
    isMockMode()
      ? mockEventsApi.listEvents(shiftKey, config)
      : realEventsApi.listEvents(shiftKey, config),
  deleteEvent: (id, config) =>
    isMockMode()
      ? mockEventsApi.deleteEvent(id, config)
      : realEventsApi.deleteEvent(id, config),
};

/**
 * Unified Reports API service instance routing to mock or real client based on VITE_API_MODE.
 */
export const reportsApi: ReportsService = {
  generateReport: (payload, config) =>
    isMockMode()
      ? mockReportsApi.generateReport(payload, config)
      : realReportsApi.generateReport(payload, config),
  listReports: (shiftKey, limitOrConfig, config) =>
    isMockMode()
      ? mockReportsApi.listReports(shiftKey, limitOrConfig, config)
      : realReportsApi.listReports(shiftKey, limitOrConfig, config),
  getReport: (id, config) =>
    isMockMode()
      ? mockReportsApi.getReport(id, config)
      : realReportsApi.getReport(id, config),
};

/**
 * Unified Admin API service instance routing to mock or real client based on VITE_API_MODE.
 */
export const adminApi: AdminService = {
  getSettings: (token, config) =>
    isMockMode()
      ? mockAdminApi.getSettings(token, config)
      : realAdminApi.getSettings(token, config),
  updateSettings: (payload, token, config) =>
    isMockMode()
      ? mockAdminApi.updateSettings(payload, token, config)
      : realAdminApi.updateSettings(payload, token, config),
};
