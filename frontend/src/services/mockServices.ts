import { ApiError, getStatusPhrase } from './errors.ts';
import type { RequestConfig } from './apiClient.ts';
import type {
  HealthResponse,
  EventResponse,
  EventCreateRequest,
  ShiftKey,
  Category,
  ReportResponse,
  ReportSummary,
  ReportGenerateRequest,
  AdminSettingsResponse,
  AdminSettingsUpdate,
  OpenAction,
} from '../types/api.ts';
import type {
  HealthService,
  EventsService,
  ReportsService,
  AdminService,
} from './types.ts';

/**
 * Generates a 32-character hexadecimal trace ID string conforming to RFC 9457 standards.
 */
export function generateTraceId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  }
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
}

/**
 * Generates a RFC 4122 v4 UUID string.
 */
export function generateUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Creates an ApiError instance with an RFC 9457 ProblemDetails payload and valid 32-character traceId.
 */
export function createMockApiError(status: number, detail: string, title?: string): ApiError {
  const phrase = title ?? getStatusPhrase(status);
  return new ApiError(status, phrase, {
    type: 'about:blank',
    title: phrase,
    status,
    detail,
    traceId: generateTraceId(),
  });
}

/**
 * Deep-clones data structures to prevent mutation leakage from the in-memory store.
 */
function cloneStoreData<T>(data: T): T {
  if (typeof structuredClone === 'function') {
    return structuredClone(data);
  }
  return JSON.parse(JSON.stringify(data)) as T;
}

// Validation constants
const SHIFT_KEY_PATTERN = /^\d{4}-\d{2}-\d{2}-(early|late|night)$/;
const UUID_PATTERN = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const MODEL_NAME_PATTERN = /^[a-zA-Z0-9._/-]+$/;
const VALID_CATEGORIES: readonly Category[] = ['downtime', 'quality', 'safety', 'info'];

export function validateShiftKey(shiftKey: unknown): asserts shiftKey is ShiftKey {
  if (typeof shiftKey !== 'string' || !SHIFT_KEY_PATTERN.test(shiftKey)) {
    throw createMockApiError(
      422,
      `Invalid shiftKey format: '${String(shiftKey)}'. Expected YYYY-MM-DD-(early|late|night).`
    );
  }
}

export function validateUuid(id: unknown): asserts id is string {
  if (typeof id !== 'string' || !UUID_PATTERN.test(id)) {
    throw createMockApiError(422, `Invalid UUID format: '${String(id)}'.`);
  }
}

// Initial seed data
export const INITIAL_SEED_EVENTS: readonly EventResponse[] = Object.freeze([
  {
    id: '41f34ec4-f489-4362-869d-9555cd9c0f98',
    shiftKey: '2026-11-14-early',
    machine: 'Press-01',
    category: 'downtime',
    note: 'Hydraulic pressure dropped suddenly, main stamping line stopped for 45 minutes.',
    createdAt: '2026-11-14T07:15:00.000Z',
  },
  {
    id: '7b4e9f2a-89a1-42e5-bc09-0d12e4f5a6b7',
    shiftKey: '2026-11-14-early',
    machine: 'Conveyor-B',
    category: 'safety',
    note: 'Oil spill observed near Conveyor-B emergency stop lever; area cordoned off with warning cones.',
    createdAt: '2026-11-14T08:30:00.000Z',
  },
  {
    id: 'c8d7e6f5-a4b3-4210-9876-543210fedcba',
    shiftKey: '2026-11-14-early',
    machine: 'Welding-Robot-03',
    category: 'quality',
    note: 'Weld seam alignment off by 1.2mm on batch #482; recalibrated optical tracking sensor.',
    createdAt: '2026-11-14T10:00:00.000Z',
  },
  {
    id: 'd9e8f7a6-b5c4-4321-8765-43210fedcba9',
    shiftKey: '2026-11-14-early',
    machine: 'Packaging-Line-02',
    category: 'info',
    note: 'Shift handed over smoothly; packaging material inventory restocked for next shift.',
    createdAt: '2026-11-14T13:45:00.000Z',
  },
]);

export const INITIAL_SEED_REPORTS: readonly ReportResponse[] = Object.freeze([
  {
    id: '2cff7f41-1053-4548-a6f5-153fc558a04d',
    shiftKey: '2026-11-14-early',
    version: 1,
    summary:
      'Shift early on 2026-11-14 completed with 4 logged events. Stamping line Press-01 experienced a 45-minute outage due to hydraulic pressure drop. A safety incident involving an oil spill at Conveyor-B was isolated with warning cones. Optical sensor recalibration on Welding-Robot-03 resolved quality variance.',
    openActions: [
      {
        action: 'Inspect hydraulic pressure valve and seals on Press-01',
        owner: 'Maintenance technician',
        priority: 'high',
      },
      {
        action: 'Complete final hazardous spill cleanup at Conveyor-B',
        owner: 'Safety coordinator',
        priority: 'high',
      },
      {
        action: 'Verify weld seam tolerance on next batch runs',
        owner: 'Quality inspector',
        priority: 'medium',
      },
    ],
    safetyNotes: [
      'Oil spill observed near Conveyor-B emergency stop lever; area cordoned off with warning cones.',
    ],
    modelUsed: 'google/gemini-3.5-flash-lite',
    eventCount: 4,
    createdAt: '2026-11-14T14:00:00.000Z',
  },
]);

export const INITIAL_SEED_ADMIN_SETTINGS: Readonly<AdminSettingsResponse> = Object.freeze({
  activeModel: 'google/gemini-3.5-flash-lite',
  fallbackModel: 'google/gemini-3.1-flash-lite',
});

// In-memory persistent stores
const eventsStore = new Map<string, EventResponse>();
const reportsStore = new Map<string, ReportResponse>();
let adminSettingsStore: AdminSettingsResponse = { ...INITIAL_SEED_ADMIN_SETTINGS };

// Configurable latency and fault injection state
let mockDelayMs = 0;

export type MockFaultTarget = 'health' | 'events' | 'reports' | 'admin' | 'all';

export interface MockFaultConfig {
  target?: MockFaultTarget;
  status?: number;
  message?: string;
  error?: ApiError;
}

let mockFault: MockFaultConfig | null = null;

/**
 * Initializes the in-memory database with fresh clones of the seed datasets.
 */
function populateInitialSeeds(): void {
  eventsStore.clear();
  for (const event of INITIAL_SEED_EVENTS) {
    eventsStore.set(event.id, cloneStoreData(event));
  }

  reportsStore.clear();
  for (const report of INITIAL_SEED_REPORTS) {
    reportsStore.set(report.id, cloneStoreData(report));
  }

  adminSettingsStore = cloneStoreData(INITIAL_SEED_ADMIN_SETTINGS);
}

// Bootstrap initial seeds
populateInitialSeeds();

/**
 * Sets artificial latency simulation in milliseconds. Defaults to 0 ms during test runs.
 */
export function setMockDelay(ms: number): void {
  mockDelayMs = Math.max(0, ms);
}

/**
 * Returns currently configured mock latency delay in milliseconds.
 */
export function getMockDelay(): number {
  return mockDelayMs;
}

/**
 * Sets or clears fault injection configuration to simulate upstream 502/LLM errors.
 */
export function setMockFailure(
  config: MockFaultConfig | MockFaultTarget | null,
  customError?: ApiError
): void {
  if (config === null) {
    mockFault = null;
    return;
  }
  if (typeof config === 'string') {
    mockFault = {
      target: config,
      status: 502,
      message: 'Simulated service failure',
      error: customError,
    };
    return;
  }
  mockFault = {
    target: config.target ?? 'all',
    status: config.status ?? 502,
    message: config.message ?? 'Simulated service failure',
    error: customError ?? config.error,
  };
}

/**
 * Restores the in-memory store to its initial seeded baseline state and resets latency/faults.
 */
export function resetMockStore(): void {
  populateInitialSeeds();
  mockDelayMs = 0;
  mockFault = null;
}

/**
 * Helper to simulate network latency if configured.
 */
async function applyMockDelay(): Promise<void> {
  if (mockDelayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, mockDelayMs));
  }
}

/**
 * Checks for injected faults targeting the invoked service.
 */
function checkMockFault(target: MockFaultTarget): void {
  if (!mockFault) return;
  if (mockFault.target === 'all' || mockFault.target === target) {
    if (mockFault.error) {
      throw mockFault.error;
    }
    const status = mockFault.status ?? 502;
    const message = mockFault.message ?? 'Simulated service failure';
    throw createMockApiError(status, message);
  }
}

/**
 * In-memory Mock implementation of HealthService.
 */
export const mockHealthApi: HealthService = {
  async getHealth(_config?: RequestConfig): Promise<HealthResponse> {
    await applyMockDelay();
    checkMockFault('health');

    return {
      status: 'ok',
      version: '0.1.0-mock',
      environment: 'mock',
    };
  },
};

/**
 * In-memory Mock implementation of EventsService.
 */
export const mockEventsApi: EventsService = {
  async listEvents(shiftKey: ShiftKey | string, _config?: RequestConfig): Promise<EventResponse[]> {
    await applyMockDelay();
    checkMockFault('events');
    validateShiftKey(shiftKey);

    const events: EventResponse[] = [];
    for (const event of eventsStore.values()) {
      if (event.shiftKey === shiftKey) {
        events.push(cloneStoreData(event));
      }
    }

    // Sort chronologically ascending by createdAt
    events.sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());
    return events;
  },

  async createEvent(payload: EventCreateRequest, _config?: RequestConfig): Promise<EventResponse> {
    await applyMockDelay();
    checkMockFault('events');

    if (!payload || typeof payload !== 'object') {
      throw createMockApiError(422, 'Request payload is required.');
    }

    validateShiftKey(payload.shiftKey);

    if (
      typeof payload.machine !== 'string' ||
      payload.machine.trim().length === 0 ||
      payload.machine.length > 100
    ) {
      throw createMockApiError(422, 'Machine identifier must be between 1 and 100 characters.');
    }

    if (!VALID_CATEGORIES.includes(payload.category)) {
      throw createMockApiError(
        422,
        `Category '${String(payload.category)}' is invalid. Must be one of: ${VALID_CATEGORIES.join(', ')}.`
      );
    }

    if (
      typeof payload.note !== 'string' ||
      payload.note.trim().length === 0 ||
      payload.note.length > 2000
    ) {
      throw createMockApiError(422, 'Note must be between 1 and 2000 characters.');
    }

    const newEvent: EventResponse = {
      id: generateUuid(),
      shiftKey: payload.shiftKey,
      machine: payload.machine.trim(),
      category: payload.category,
      note: payload.note.trim(),
      createdAt: new Date().toISOString(),
    };

    eventsStore.set(newEvent.id, cloneStoreData(newEvent));
    return cloneStoreData(newEvent);
  },

  async deleteEvent(id: string, _config?: RequestConfig): Promise<void> {
    await applyMockDelay();
    checkMockFault('events');
    validateUuid(id);

    if (!eventsStore.has(id)) {
      throw createMockApiError(404, `Event '${id}' not found`);
    }

    eventsStore.delete(id);
  },
};

/**
 * In-memory Mock implementation of ReportsService.
 */
export const mockReportsApi: ReportsService = {
  async generateReport(
    payload: ReportGenerateRequest,
    _config?: RequestConfig
  ): Promise<ReportResponse> {
    await applyMockDelay();
    checkMockFault('reports');

    if (!payload || typeof payload !== 'object') {
      throw createMockApiError(422, 'Request payload is required.');
    }

    validateShiftKey(payload.shiftKey);

    const shiftEvents: EventResponse[] = [];
    for (const event of eventsStore.values()) {
      if (event.shiftKey === payload.shiftKey) {
        shiftEvents.push(event);
      }
    }

    if (shiftEvents.length === 0) {
      throw createMockApiError(422, 'No events found for shift', 'Unprocessable Entity');
    }

    // Determine sequential version for this shiftKey
    let maxVersion = 0;
    for (const report of reportsStore.values()) {
      if (report.shiftKey === payload.shiftKey && report.version > maxVersion) {
        maxVersion = report.version;
      }
    }
    const version = maxVersion + 1;

    // Categorized breakdown for deterministic synthesis
    const safetyEvents = shiftEvents.filter((e) => e.category === 'safety');
    const downtimeEvents = shiftEvents.filter((e) => e.category === 'downtime');
    const qualityEvents = shiftEvents.filter((e) => e.category === 'quality');
    const infoEvents = shiftEvents.filter((e) => e.category === 'info');

    // Synthesize concise summary
    const summarySentences: string[] = [
      `Shift ${payload.shiftKey} completed with ${shiftEvents.length} operational event(s) logged.`,
    ];
    if (downtimeEvents.length > 0) {
      summarySentences.push(
        `Downtime recorded on ${downtimeEvents.map((e) => e.machine).join(', ')}: ${downtimeEvents[0].note}`
      );
    }
    if (safetyEvents.length > 0) {
      summarySentences.push(
        `Safety incident noted on ${safetyEvents.map((e) => e.machine).join(', ')}: ${safetyEvents[0].note}`
      );
    }
    if (qualityEvents.length > 0) {
      summarySentences.push(
        `Quality observation recorded on ${qualityEvents.map((e) => e.machine).join(', ')}: ${qualityEvents[0].note}`
      );
    }
    if (infoEvents.length > 0 && summarySentences.length < 5) {
      summarySentences.push(`Operational update: ${infoEvents[0].note}`);
    }

    const summary = summarySentences.slice(0, 5).join(' ');

    // Synthesize open actions
    const openActions: OpenAction[] = [];
    for (const e of safetyEvents) {
      openActions.push({
        action: `Remediate safety hazard at ${e.machine}: ${e.note.slice(0, 80)}`,
        owner: 'Safety officer',
        priority: 'high',
      });
    }
    for (const e of downtimeEvents) {
      openActions.push({
        action: `Perform mechanical diagnostic and repair on ${e.machine}`,
        owner: 'Maintenance technician',
        priority: 'high',
      });
    }
    for (const e of qualityEvents) {
      openActions.push({
        action: `Inspect part tolerances and recalibrate ${e.machine}`,
        owner: 'Quality inspector',
        priority: 'medium',
      });
    }
    for (const e of infoEvents) {
      openActions.push({
        action: `Verify operational handover status for ${e.machine}`,
        owner: 'Shift lead',
        priority: 'low',
      });
    }

    if (openActions.length === 0) {
      openActions.push({
        action: 'Review shift logs with oncoming crew',
        owner: 'Shift lead',
        priority: 'medium',
      });
    }

    // Zero-omission safety notes
    const safetyNotes: string[] =
      safetyEvents.length > 0
        ? safetyEvents.map((e) => e.note)
        : ['No safety incidents reported for shift.'];

    const newReport: ReportResponse = {
      id: generateUuid(),
      shiftKey: payload.shiftKey,
      version,
      summary,
      openActions,
      safetyNotes,
      modelUsed: adminSettingsStore.activeModel,
      eventCount: shiftEvents.length,
      createdAt: new Date().toISOString(),
    };

    reportsStore.set(newReport.id, cloneStoreData(newReport));
    return cloneStoreData(newReport);
  },

  async listReports(
    shiftKey?: ShiftKey | string,
    limitOrConfig?: number | RequestConfig,
    _config?: RequestConfig
  ): Promise<ReportSummary[]> {
    await applyMockDelay();
    checkMockFault('reports');

    const limit = typeof limitOrConfig === 'number' ? limitOrConfig : undefined;

    if (shiftKey !== undefined && shiftKey !== '') {
      validateShiftKey(shiftKey);
    }

    if (limit !== undefined) {
      if (typeof limit !== 'number' || limit < 1 || !Number.isInteger(limit)) {
        throw createMockApiError(422, 'Limit must be a positive integer greater than or equal to 1.');
      }
    }

    const effectiveLimit = limit ?? 20;

    const summaries: ReportSummary[] = [];
    for (const report of reportsStore.values()) {
      if (!shiftKey || report.shiftKey === shiftKey) {
        summaries.push({
          id: report.id,
          shiftKey: report.shiftKey,
          version: report.version,
          modelUsed: report.modelUsed,
          eventCount: report.eventCount,
          createdAt: report.createdAt,
        });
      }
    }

    // Sort descending by createdAt, secondary sort by version descending
    summaries.sort((a, b) => {
      const timeDiff = new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
      if (timeDiff !== 0) return timeDiff;
      return b.version - a.version;
    });

    return cloneStoreData(summaries.slice(0, effectiveLimit));
  },

  async getReport(id: string, _config?: RequestConfig): Promise<ReportResponse> {
    await applyMockDelay();
    checkMockFault('reports');
    validateUuid(id);

    const report = reportsStore.get(id);
    if (!report) {
      throw createMockApiError(404, `Report '${id}' not found`);
    }

    return cloneStoreData(report);
  },
};

/**
 * In-memory Mock implementation of AdminService.
 */
export const mockAdminApi: AdminService = {
  async getSettings(token?: string, _config?: RequestConfig): Promise<AdminSettingsResponse> {
    await applyMockDelay();
    checkMockFault('admin');

    if (!token || typeof token !== 'string' || token.trim().length === 0) {
      throw createMockApiError(401, 'Unauthorized');
    }

    return cloneStoreData(adminSettingsStore);
  },

  async updateSettings(
    payload: AdminSettingsUpdate,
    token?: string,
    _config?: RequestConfig
  ): Promise<AdminSettingsResponse> {
    await applyMockDelay();
    checkMockFault('admin');

    if (!token || typeof token !== 'string' || token.trim().length === 0) {
      throw createMockApiError(401, 'Unauthorized');
    }

    if (!payload || typeof payload !== 'object') {
      throw createMockApiError(422, 'Request payload is required.');
    }

    const hasActive = payload.activeModel !== undefined && payload.activeModel !== null;
    const hasFallback = payload.fallbackModel !== undefined && payload.fallbackModel !== null;

    if (!hasActive && !hasFallback) {
      throw createMockApiError(
        422,
        'At least one of activeModel or fallbackModel must be provided.'
      );
    }

    if (hasActive) {
      const active = payload.activeModel as string;
      if (
        typeof active !== 'string' ||
        active.length < 1 ||
        active.length > 128 ||
        !MODEL_NAME_PATTERN.test(active)
      ) {
        throw createMockApiError(
          422,
          `Invalid activeModel '${String(active)}'. Must match ^[a-zA-Z0-9._/-]+$ with max length 128.`
        );
      }
    }

    if (hasFallback) {
      const fallback = payload.fallbackModel as string;
      if (
        typeof fallback !== 'string' ||
        fallback.length < 1 ||
        fallback.length > 128 ||
        !MODEL_NAME_PATTERN.test(fallback)
      ) {
        throw createMockApiError(
          422,
          `Invalid fallbackModel '${String(fallback)}'. Must match ^[a-zA-Z0-9._/-]+$ with max length 128.`
        );
      }
    }

    if (hasActive) {
      adminSettingsStore.activeModel = (payload.activeModel as string).trim();
    }
    if (hasFallback) {
      adminSettingsStore.fallbackModel = (payload.fallbackModel as string).trim();
    }

    return cloneStoreData(adminSettingsStore);
  },
};
