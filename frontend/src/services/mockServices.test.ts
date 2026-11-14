import { describe, it, expect, beforeEach } from 'vitest';
import {
  mockHealthApi,
  mockEventsApi,
  mockReportsApi,
  mockAdminApi,
  resetMockStore,
  setMockDelay,
  getMockDelay,
  setMockFailure,
  generateTraceId,
  generateUuid,
  createMockApiError,
  INITIAL_SEED_EVENTS,
  INITIAL_SEED_REPORTS,
  INITIAL_SEED_ADMIN_SETTINGS,
} from './mockServices.ts';
import {
  healthApi,
  eventsApi,
  reportsApi,
  adminApi,
  isMockMode,
  setApiModeOverride,
} from './index.ts';
import { ApiError, isApiError } from './errors.ts';
import type { EventCreateRequest, AdminSettingsUpdate } from '../types/api.ts';

describe('mockServices', () => {
  beforeEach(() => {
    resetMockStore();
    setApiModeOverride(null);
  });

  describe('traceId & utility helpers', () => {
    it('generateTraceId produces a 32-character lowercase hex string', () => {
      const traceId1 = generateTraceId();
      const traceId2 = generateTraceId();

      expect(traceId1).toMatch(/^[0-9a-f]{32}$/);
      expect(traceId2).toMatch(/^[0-9a-f]{32}$/);
      expect(traceId1).not.toBe(traceId2);
    });

    it('generateUuid produces a valid v4 UUID format', () => {
      const uuid1 = generateUuid();
      const uuid2 = generateUuid();

      expect(uuid1).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
      expect(uuid2).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
      expect(uuid1).not.toBe(uuid2);
    });

    it('createMockApiError creates a valid ApiError with RFC 9457 ProblemDetails and 32-character traceId', () => {
      const error = createMockApiError(422, 'Validation failed for field X');

      expect(isApiError(error)).toBe(true);
      expect(error.status).toBe(422);
      expect(error.statusText).toBe('Unprocessable Entity');
      expect(error.problemDetails.type).toBe('about:blank');
      expect(error.problemDetails.title).toBe('Unprocessable Entity');
      expect(error.problemDetails.status).toBe(422);
      expect(error.problemDetails.detail).toBe('Validation failed for field X');
      expect(error.problemDetails.traceId).toMatch(/^[0-9a-f]{32}$/);
    });
  });

  describe('mockHealthApi', () => {
    it('getHealth returns { status: "ok", version: "0.1.0-mock", environment: "mock" }', async () => {
      const res = await mockHealthApi.getHealth();
      expect(res).toEqual({
        status: 'ok',
        version: '0.1.0-mock',
        environment: 'mock',
      });
    });
  });

  describe('mockEventsApi', () => {
    describe('listEvents', () => {
      it('returns pre-seeded events for 2026-11-14-early with all 4 categories', async () => {
        const events = await mockEventsApi.listEvents('2026-11-14-early');

        expect(events).toHaveLength(4);
        const categories = events.map((e) => e.category);
        expect(categories).toContain('downtime');
        expect(categories).toContain('safety');
        expect(categories).toContain('quality');
        expect(categories).toContain('info');
      });

      it('sorts events chronologically ascending by createdAt', async () => {
        const events = await mockEventsApi.listEvents('2026-11-14-early');

        for (let i = 0; i < events.length - 1; i++) {
          const current = new Date(events[i].createdAt).getTime();
          const next = new Date(events[i + 1].createdAt).getTime();
          expect(current).toBeLessThanOrEqual(next);
        }
      });

      it('returns an empty array [] for a valid shiftKey that has no events', async () => {
        const events = await mockEventsApi.listEvents('2026-11-15-night');
        expect(events).toEqual([]);
      });

      it('throws 422 ApiError with valid traceId when shiftKey is invalid', async () => {
        const invalidKeys = [
          'invalid-shift',
          '2026-11-14',
          '2026-11-14-afternoon',
          '26-11-14-early',
          '2026-1-1-early',
          '',
        ];

        for (const key of invalidKeys) {
          try {
            await mockEventsApi.listEvents(key);
            expect.unreachable(`Expected listEvents('${key}') to throw`);
          } catch (err) {
            expect(isApiError(err)).toBe(true);
            const apiError = err as ApiError;
            expect(apiError.status).toBe(422);
            expect(apiError.statusText).toBe('Unprocessable Entity');
            expect(apiError.problemDetails.traceId).toMatch(/^[0-9a-f]{32}$/);
            expect(apiError.problemDetails.detail).toContain('Invalid shiftKey format');
          }
        }
      });
    });

    describe('createEvent', () => {
      it('creates and persists an event, returning 201 EventResponse with UUID and ISO createdAt', async () => {
        const payload: EventCreateRequest = {
          shiftKey: '2026-11-15-early',
          machine: 'Lathe-04',
          category: 'quality',
          note: 'Spindle vibration exceeded threshold by 0.3mm/s.',
        };

        const created = await mockEventsApi.createEvent(payload);

        expect(created.id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
        expect(created.shiftKey).toBe('2026-11-15-early');
        expect(created.machine).toBe('Lathe-04');
        expect(created.category).toBe('quality');
        expect(created.note).toBe('Spindle vibration exceeded threshold by 0.3mm/s.');
        expect(new Date(created.createdAt).toISOString()).toBe(created.createdAt);

        // Verify persistence
        const retrieved = await mockEventsApi.listEvents('2026-11-15-early');
        expect(retrieved).toHaveLength(1);
        expect(retrieved[0].id).toBe(created.id);
      });

      it('throws 422 ApiError when shiftKey is invalid', async () => {
        await expect(
          mockEventsApi.createEvent({
            shiftKey: 'invalid-shift',
            machine: 'Press-01',
            category: 'downtime',
            note: 'Failure occurred',
          })
        ).rejects.toThrowError(ApiError);
      });

      it('throws 422 ApiError when machine is missing or invalid length', async () => {
        // Empty string
        await expect(
          mockEventsApi.createEvent({
            shiftKey: '2026-11-14-early',
            machine: '   ',
            category: 'downtime',
            note: 'Failure occurred',
          })
        ).rejects.toThrowError(ApiError);

        // Exceeds 100 characters
        await expect(
          mockEventsApi.createEvent({
            shiftKey: '2026-11-14-early',
            machine: 'M'.repeat(101),
            category: 'downtime',
            note: 'Failure occurred',
          })
        ).rejects.toThrowError(ApiError);
      });

      it('throws 422 ApiError when category is not one of 4 allowed categories', async () => {
        await expect(
          mockEventsApi.createEvent({
            shiftKey: '2026-11-14-early',
            machine: 'Press-01',
            // @ts-expect-error Testing invalid category runtime validation
            category: 'maintenance',
            note: 'Scheduled maintenance check',
          })
        ).rejects.toThrowError(ApiError);
      });

      it('throws 422 ApiError when note is empty or exceeds 2000 characters', async () => {
        // Empty note
        await expect(
          mockEventsApi.createEvent({
            shiftKey: '2026-11-14-early',
            machine: 'Press-01',
            category: 'info',
            note: '',
          })
        ).rejects.toThrowError(ApiError);

        // Exceeds 2000 characters
        await expect(
          mockEventsApi.createEvent({
            shiftKey: '2026-11-14-early',
            machine: 'Press-01',
            category: 'info',
            note: 'A'.repeat(2001),
          })
        ).rejects.toThrowError(ApiError);
      });
    });

    describe('deleteEvent', () => {
      it('throws 422 ApiError if UUID is malformed', async () => {
        try {
          await mockEventsApi.deleteEvent('not-a-valid-uuid');
          expect.unreachable('Expected deleteEvent to throw');
        } catch (err) {
          expect(isApiError(err)).toBe(true);
          const apiError = err as ApiError;
          expect(apiError.status).toBe(422);
          expect(apiError.problemDetails.detail).toContain('Invalid UUID format');
        }
      });

      it('deletes an existing event and subsequent delete throws 404', async () => {
        const seedEvent = INITIAL_SEED_EVENTS[0];

        // First delete succeeds
        await expect(mockEventsApi.deleteEvent(seedEvent.id)).resolves.toBeUndefined();

        // Second delete of same ID throws 404
        try {
          await mockEventsApi.deleteEvent(seedEvent.id);
          expect.unreachable('Expected second deleteEvent to throw 404');
        } catch (err) {
          expect(isApiError(err)).toBe(true);
          const apiError = err as ApiError;
          expect(apiError.status).toBe(404);
          expect(apiError.statusText).toBe('Not Found');
          expect(apiError.problemDetails.detail).toBe(`Event '${seedEvent.id}' not found`);
          expect(apiError.problemDetails.traceId).toMatch(/^[0-9a-f]{32}$/);
        }

        // Verify event was removed from list
        const remaining = await mockEventsApi.listEvents('2026-11-14-early');
        expect(remaining.some((e) => e.id === seedEvent.id)).toBe(false);
      });

      it('throws 404 ApiError when deleting a nonexistent UUID', async () => {
        const randomUuid = '00000000-0000-4000-8000-000000000000';
        try {
          await mockEventsApi.deleteEvent(randomUuid);
          expect.unreachable('Expected deleteEvent to throw 404');
        } catch (err) {
          expect(isApiError(err)).toBe(true);
          const apiError = err as ApiError;
          expect(apiError.status).toBe(404);
          expect(apiError.problemDetails.detail).toBe(`Event '${randomUuid}' not found`);
        }
      });
    });
  });

  describe('mockReportsApi', () => {
    describe('generateReport', () => {
      it('throws 422 ApiError if shiftKey is invalid', async () => {
        await expect(
          mockReportsApi.generateReport({ shiftKey: 'bad-key' })
        ).rejects.toThrowError(ApiError);
      });

      it('throws 422 ApiError ("No events found for shift") if shift has 0 events', async () => {
        try {
          await mockReportsApi.generateReport({ shiftKey: '2026-11-20-night' });
          expect.unreachable('Expected generateReport to throw 422');
        } catch (err) {
          expect(isApiError(err)).toBe(true);
          const apiError = err as ApiError;
          expect(apiError.status).toBe(422);
          expect(apiError.problemDetails.title).toBe('Unprocessable Entity');
          expect(apiError.problemDetails.detail).toBe('No events found for shift');
          expect(apiError.problemDetails.traceId).toMatch(/^[0-9a-f]{32}$/);
        }
      });

      it('synthesizes report and increments sequential version for shiftKey', async () => {
        // Initial seed report for 2026-11-14-early is version 1
        const reportV2 = await mockReportsApi.generateReport({ shiftKey: '2026-11-14-early' });

        expect(reportV2.shiftKey).toBe('2026-11-14-early');
        expect(reportV2.version).toBe(2);
        expect(reportV2.eventCount).toBe(4);
        expect(reportV2.modelUsed).toBe('google/gemini-3.5-flash-lite');
        expect(typeof reportV2.summary).toBe('string');
        expect(reportV2.summary.length).toBeGreaterThan(10);
        expect(reportV2.openActions.length).toBeGreaterThan(0);
        expect(reportV2.openActions[0]).toHaveProperty('action');
        expect(reportV2.openActions[0]).toHaveProperty('owner');
        expect(['high', 'medium', 'low']).toContain(reportV2.openActions[0].priority);
        expect(reportV2.safetyNotes.length).toBeGreaterThan(0);

        // Generating a third time increments version to 3
        const reportV3 = await mockReportsApi.generateReport({ shiftKey: '2026-11-14-early' });
        expect(reportV3.version).toBe(3);
      });

      it('starts version at 1 for a new shift with newly created events', async () => {
        await mockEventsApi.createEvent({
          shiftKey: '2026-11-16-early',
          machine: 'Robot-Arm-01',
          category: 'info',
          note: 'Line began normal production run.',
        });

        const report = await mockReportsApi.generateReport({ shiftKey: '2026-11-16-early' });
        expect(report.shiftKey).toBe('2026-11-16-early');
        expect(report.version).toBe(1);
        expect(report.eventCount).toBe(1);
      });
    });

    describe('listReports', () => {
      it('returns array of ReportSummary sorted descending by createdAt / version', async () => {
        // Generate a second report to verify sorting
        await mockReportsApi.generateReport({ shiftKey: '2026-11-14-early' });

        const summaries = await mockReportsApi.listReports();
        expect(summaries.length).toBeGreaterThanOrEqual(2);

        for (let i = 0; i < summaries.length - 1; i++) {
          const current = new Date(summaries[i].createdAt).getTime();
          const next = new Date(summaries[i + 1].createdAt).getTime();
          expect(current).toBeGreaterThanOrEqual(next);
        }
      });

      it('filters summaries by shiftKey when provided', async () => {
        // Create an event and report on a distinct shift
        await mockEventsApi.createEvent({
          shiftKey: '2026-11-17-late',
          machine: 'Press-02',
          category: 'info',
          note: 'Shift handover routine complete',
        });
        await mockReportsApi.generateReport({ shiftKey: '2026-11-17-late' });

        const earlySummaries = await mockReportsApi.listReports('2026-11-14-early');
        expect(earlySummaries.every((s) => s.shiftKey === '2026-11-14-early')).toBe(true);

        const lateSummaries = await mockReportsApi.listReports('2026-11-17-late');
        expect(lateSummaries.every((s) => s.shiftKey === '2026-11-17-late')).toBe(true);
        expect(lateSummaries).toHaveLength(1);
      });

      it('throws 422 ApiError if shiftKey is malformed', async () => {
        await expect(mockReportsApi.listReports('invalid-shift')).rejects.toThrowError(ApiError);
      });

      it('caps results at limit and throws 422 if limit < 1', async () => {
        // Seed another report
        await mockReportsApi.generateReport({ shiftKey: '2026-11-14-early' });

        const capped = await mockReportsApi.listReports(undefined, 1);
        expect(capped).toHaveLength(1);

        await expect(mockReportsApi.listReports(undefined, 0)).rejects.toThrowError(ApiError);
        await expect(mockReportsApi.listReports(undefined, -5)).rejects.toThrowError(ApiError);
      });
    });

    describe('getReport', () => {
      it('validates UUID format and throws 422 if malformed', async () => {
        try {
          await mockReportsApi.getReport('bad-uuid');
          expect.unreachable('Expected getReport to throw 422');
        } catch (err) {
          expect(isApiError(err)).toBe(true);
          const apiError = err as ApiError;
          expect(apiError.status).toBe(422);
          expect(apiError.problemDetails.detail).toContain('Invalid UUID format');
        }
      });

      it('returns full immutable ReportResponse snapshot for existing ID', async () => {
        const seedReport = INITIAL_SEED_REPORTS[0];
        const report = await mockReportsApi.getReport(seedReport.id);

        expect(report.id).toBe(seedReport.id);
        expect(report.shiftKey).toBe(seedReport.shiftKey);
        expect(report.version).toBe(seedReport.version);
        expect(report.summary).toBe(seedReport.summary);
        expect(report.openActions).toEqual(seedReport.openActions);
        expect(report.safetyNotes).toEqual(seedReport.safetyNotes);
      });

      it('throws 404 ApiError with detail "Report \'<id>\' not found" if ID does not exist', async () => {
        const nonExistentUuid = '99999999-9999-4999-8999-999999999999';
        try {
          await mockReportsApi.getReport(nonExistentUuid);
          expect.unreachable('Expected getReport to throw 404');
        } catch (err) {
          expect(isApiError(err)).toBe(true);
          const apiError = err as ApiError;
          expect(apiError.status).toBe(404);
          expect(apiError.problemDetails.detail).toBe(`Report '${nonExistentUuid}' not found`);
          expect(apiError.problemDetails.traceId).toMatch(/^[0-9a-f]{32}$/);
        }
      });
    });
  });

  describe('mockAdminApi', () => {
    describe('getSettings', () => {
      it('throws 401 ApiError (detail: "Unauthorized") if token is missing or empty', async () => {
        const emptyTokens = [undefined, '', '   '];

        for (const token of emptyTokens) {
          try {
            await mockAdminApi.getSettings(token);
            expect.unreachable(`Expected getSettings(${token}) to throw 401`);
          } catch (err) {
            expect(isApiError(err)).toBe(true);
            const apiError = err as ApiError;
            expect(apiError.status).toBe(401);
            expect(apiError.statusText).toBe('Unauthorized');
            expect(apiError.problemDetails.detail).toBe('Unauthorized');
            expect(apiError.problemDetails.traceId).toMatch(/^[0-9a-f]{32}$/);
          }
        }
      });

      it('returns AdminSettingsResponse when authenticated with valid token', async () => {
        const settings = await mockAdminApi.getSettings('admin-secret-token');

        expect(settings).toEqual({
          activeModel: 'google/gemini-3.5-flash-lite',
          fallbackModel: 'google/gemini-3.1-flash-lite',
        });
      });
    });

    describe('updateSettings', () => {
      it('throws 401 ApiError if token is missing or empty', async () => {
        const payload: AdminSettingsUpdate = { activeModel: 'google/gemini-3.5-pro' };

        await expect(mockAdminApi.updateSettings(payload)).rejects.toThrowError(ApiError);
        await expect(mockAdminApi.updateSettings(payload, '')).rejects.toThrowError(ApiError);
      });

      it('throws 422 ApiError if payload does not contain activeModel or fallbackModel', async () => {
        await expect(mockAdminApi.updateSettings({}, 'valid-token')).rejects.toThrowError(ApiError);
      });

      it('throws 422 ApiError if model name fails regex validation', async () => {
        const invalidModels = ['invalid model with spaces', 'model#with$symbols', ''];

        for (const model of invalidModels) {
          try {
            await mockAdminApi.updateSettings({ activeModel: model }, 'valid-token');
            expect.unreachable(`Expected model '${model}' to fail validation`);
          } catch (err) {
            expect(isApiError(err)).toBe(true);
            const apiError = err as ApiError;
            expect(apiError.status).toBe(422);
            expect(apiError.problemDetails.detail).toContain('Invalid activeModel');
          }
        }
      });

      it('updates models and returns updated AdminSettingsResponse', async () => {
        const updated = await mockAdminApi.updateSettings(
          {
            activeModel: 'google/gemini-3.5-pro',
            fallbackModel: 'google/gemini-3.5-flash',
          },
          'valid-token'
        );

        expect(updated.activeModel).toBe('google/gemini-3.5-pro');
        expect(updated.fallbackModel).toBe('google/gemini-3.5-flash');

        // Subsequent getSettings returns updated values
        const retrieved = await mockAdminApi.getSettings('valid-token');
        expect(retrieved.activeModel).toBe('google/gemini-3.5-pro');
        expect(retrieved.fallbackModel).toBe('google/gemini-3.5-flash');
      });

      it('allows partial update of only activeModel', async () => {
        const updated = await mockAdminApi.updateSettings(
          { activeModel: 'google/gemini-3.5-ultra' },
          'valid-token'
        );

        expect(updated.activeModel).toBe('google/gemini-3.5-ultra');
        expect(updated.fallbackModel).toBe('google/gemini-3.1-flash-lite');
      });
    });
  });

  describe('immutability & mutation prevention', () => {
    it('mutations on returned listEvents results do not leak to store', async () => {
      const events = await mockEventsApi.listEvents('2026-11-14-early');
      expect(events.length).toBeGreaterThan(0);

      // Mutate the local array item
      events[0].machine = 'MUTATED_MACHINE';
      events[0].note = 'MUTATED_NOTE';

      const freshEvents = await mockEventsApi.listEvents('2026-11-14-early');
      expect(freshEvents[0].machine).not.toBe('MUTATED_MACHINE');
      expect(freshEvents[0].note).not.toBe('MUTATED_NOTE');
    });

    it('mutations on returned getReport results do not leak to store', async () => {
      const seedReport = INITIAL_SEED_REPORTS[0];
      const report = await mockReportsApi.getReport(seedReport.id);

      report.summary = 'MUTATED_SUMMARY';
      report.openActions.push({
        action: 'MUTATED_ACTION',
        owner: 'Nobody',
        priority: 'high',
      });

      const freshReport = await mockReportsApi.getReport(seedReport.id);
      expect(freshReport.summary).toBe(seedReport.summary);
      expect(freshReport.openActions).toHaveLength(seedReport.openActions.length);
    });

    it('mutations on returned getSettings results do not leak to store', async () => {
      const settings = await mockAdminApi.getSettings('token');
      settings.activeModel = 'MUTATED_MODEL';

      const freshSettings = await mockAdminApi.getSettings('token');
      expect(freshSettings.activeModel).toBe(INITIAL_SEED_ADMIN_SETTINGS.activeModel);
    });
  });

  describe('configurable latency simulation', () => {
    it('setMockDelay sets artificial delay and defaults to 0', async () => {
      expect(getMockDelay()).toBe(0);

      setMockDelay(20);
      expect(getMockDelay()).toBe(20);

      const start = Date.now();
      await mockHealthApi.getHealth();
      const elapsed = Date.now() - start;

      expect(elapsed).toBeGreaterThanOrEqual(15);

      setMockDelay(0);
      expect(getMockDelay()).toBe(0);
    });
  });

  describe('fault injection helper', () => {
    it('setMockFailure simulates 502 Bad Gateway / upstream error on target service', async () => {
      setMockFailure('reports');

      // Health still works normally
      await expect(mockHealthApi.getHealth()).resolves.toBeDefined();

      // Reports service throws 502
      try {
        await mockReportsApi.listReports();
        expect.unreachable('Expected mockReportsApi to throw 502');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        const apiError = err as ApiError;
        expect(apiError.status).toBe(502);
        expect(apiError.statusText).toBe('Bad Gateway');
        expect(apiError.problemDetails.traceId).toMatch(/^[0-9a-f]{32}$/);
      }

      // Clearing fault restores operation
      setMockFailure(null);
      await expect(mockReportsApi.listReports()).resolves.toBeDefined();
    });

    it('setMockFailure allows custom status and message across all services', async () => {
      setMockFailure({
        target: 'all',
        status: 503,
        message: 'LLM inference service overloaded',
      });

      try {
        await mockHealthApi.getHealth();
        expect.unreachable('Expected mockHealthApi to throw 503');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        const apiError = err as ApiError;
        expect(apiError.status).toBe(503);
        expect(apiError.problemDetails.detail).toBe('LLM inference service overloaded');
      }

      setMockFailure(null);
    });
  });

  describe('resetMockStore helper', () => {
    it('restores all stores and settings to initial baseline state', async () => {
      // Modify events
      await mockEventsApi.createEvent({
        shiftKey: '2026-11-14-early',
        machine: 'Temporary-01',
        category: 'info',
        note: 'Temp note',
      });
      await mockEventsApi.deleteEvent(INITIAL_SEED_EVENTS[0].id);

      // Modify settings
      await mockAdminApi.updateSettings({ activeModel: 'custom/model' }, 'token');

      // Set latency & failure
      setMockDelay(50);
      setMockFailure('health');

      // Reset
      resetMockStore();

      expect(getMockDelay()).toBe(0);
      // Health works without fault
      await expect(mockHealthApi.getHealth()).resolves.toBeDefined();

      // Events restored
      const events = await mockEventsApi.listEvents('2026-11-14-early');
      expect(events).toHaveLength(INITIAL_SEED_EVENTS.length);
      expect(events.some((e) => e.id === INITIAL_SEED_EVENTS[0].id)).toBe(true);

      // Settings restored
      const settings = await mockAdminApi.getSettings('token');
      expect(settings).toEqual(INITIAL_SEED_ADMIN_SETTINGS);
    });
  });

  describe('centralized service resolver routing', () => {
    it('isMockMode returns false by default or when set to "real"', () => {
      setApiModeOverride('real');
      expect(isMockMode()).toBe(false);

      setApiModeOverride('mock');
      expect(isMockMode()).toBe(true);
    });

    it('unified service instances route to mock when mode is "mock"', async () => {
      setApiModeOverride('mock');

      const health = await healthApi.getHealth();
      expect(health.version).toBe('0.1.0-mock');
      expect(health.environment).toBe('mock');

      const events = await eventsApi.listEvents('2026-11-14-early');
      expect(events).toHaveLength(4);

      const created = await eventsApi.createEvent({
        shiftKey: '2026-11-14-early',
        machine: 'Resolved-01',
        category: 'info',
        note: 'Created via unified resolver',
      });
      expect(created.machine).toBe('Resolved-01');

      const reports = await reportsApi.listReports('2026-11-14-early');
      expect(reports.length).toBeGreaterThanOrEqual(1);

      const reportDetail = await reportsApi.getReport(reports[0].id);
      expect(reportDetail.id).toBe(reports[0].id);

      const generated = await reportsApi.generateReport({ shiftKey: '2026-11-14-early' });
      expect(generated.shiftKey).toBe('2026-11-14-early');

      const admin = await adminApi.getSettings('token');
      expect(admin.activeModel).toBe('google/gemini-3.5-flash-lite');

      const updatedAdmin = await adminApi.updateSettings(
        { activeModel: 'google/gemini-3.5-flash' },
        'token'
      );
      expect(updatedAdmin.activeModel).toBe('google/gemini-3.5-flash');

      await expect(eventsApi.deleteEvent(created.id)).resolves.toBeUndefined();
    });
  });
});
