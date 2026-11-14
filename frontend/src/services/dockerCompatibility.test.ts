import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { eventsApi } from './eventsApi.ts';
import { reportsApi } from './reportsApi.ts';
import { adminApi } from './adminApi.ts';
import type {
  EventCreateRequest,
  ReportGenerateRequest,
  AdminSettingsUpdate,
} from '../types/api.ts';

describe('Docker and Direct API Compatibility (Issue #23)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('eventsApi direct compatibility', () => {
    it('creates an event successfully and returns populated shiftKey and createdAt with dual properties', async () => {
      const payload: EventCreateRequest = {
        shiftKey: '2026-11-14-early',
        machine: 'Press-01',
        category: 'downtime',
        note: 'Hydraulic pressure drop on main line',
      };

      // Mock backend returning dual fields
      const backendDualResponse = {
        id: '41f34ec4-f489-4362-869d-9555cd9c0f98',
        shift_key: '2026-11-14-early',
        shiftKey: '2026-11-14-early',
        machine: 'Press-01',
        category: 'downtime',
        note: 'Hydraulic pressure drop on main line',
        created_at: '2026-11-14T06:45:00Z',
        createdAt: '2026-11-14T06:45:00Z',
      };

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(backendDualResponse), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const created = await eventsApi.createEvent(payload);

      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/events',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(payload),
        })
      );

      expect(created.id).toBe('41f34ec4-f489-4362-869d-9555cd9c0f98');
      expect(created.shiftKey).toBe('2026-11-14-early');
      expect(created.createdAt).toBe('2026-11-14T06:45:00Z');
      expect((created as unknown as Record<string, unknown>).shift_key).toBe('2026-11-14-early');
      expect((created as unknown as Record<string, unknown>).created_at).toBe('2026-11-14T06:45:00Z');
    });

    it('creates an event successfully when backend returns pure snake_case', async () => {
      const payload: EventCreateRequest = {
        shiftKey: '2026-11-14-early',
        machine: 'Conveyor-B',
        category: 'safety',
        note: 'Safety cord inspected',
      };

      const backendSnakeResponse = {
        id: '52f34ec4-f489-4362-869d-9555cd9c0f99',
        shift_key: '2026-11-14-early',
        machine: 'Conveyor-B',
        category: 'safety',
        note: 'Safety cord inspected',
        created_at: '2026-11-14T07:00:00Z',
      };

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(backendSnakeResponse), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const created = await eventsApi.createEvent(payload);

      expect(created.shiftKey).toBe('2026-11-14-early');
      expect(created.createdAt).toBe('2026-11-14T07:00:00Z');
    });

    it('retrieves events filtered by shiftKey and returns populated shiftKey and createdAt', async () => {
      const backendEvents = [
        {
          id: '11111111-1111-1111-1111-111111111111',
          shift_key: '2026-11-14-late',
          shiftKey: '2026-11-14-late',
          machine: 'Press-02',
          category: 'quality',
          note: 'Part dimension check passed',
          created_at: '2026-11-14T15:30:00Z',
          createdAt: '2026-11-14T15:30:00Z',
        },
      ];

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(backendEvents), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const list = await eventsApi.listEvents('2026-11-14-late');

      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/events?shiftKey=2026-11-14-late',
        expect.objectContaining({ method: 'GET' })
      );

      expect(list).toHaveLength(1);
      expect(list[0].shiftKey).toBe('2026-11-14-late');
      expect(list[0].createdAt).toBe('2026-11-14T15:30:00Z');
      expect((list[0] as unknown as Record<string, unknown>).shift_key).toBe('2026-11-14-late');
      expect((list[0] as unknown as Record<string, unknown>).created_at).toBe('2026-11-14T15:30:00Z');
    });
  });

  describe('reportsApi direct compatibility', () => {
    it('initiates report generation with shiftKey and returns structured report with openActions, safetyNotes, modelUsed', async () => {
      const payload: ReportGenerateRequest = {
        shiftKey: '2026-11-14-early',
      };

      const backendReport = {
        id: '2cff7f41-1053-4548-a6f5-153fc558a04d',
        shift_key: '2026-11-14-early',
        shiftKey: '2026-11-14-early',
        version: 1,
        summary: 'All stations operated smoothly during the early shift.',
        open_actions: [
          {
            action: 'Clean up oil spill near Conveyor-B',
            owner: 'Shift lead',
            priority: 'high',
          },
        ],
        openActions: [
          {
            action: 'Clean up oil spill near Conveyor-B',
            owner: 'Shift lead',
            priority: 'high',
          },
        ],
        safety_notes: ['Oil spill cordoned off with cones'],
        safetyNotes: ['Oil spill cordoned off with cones'],
        model_used: 'google/gemini-3.5-flash-lite',
        modelUsed: 'google/gemini-3.5-flash-lite',
        event_count: 2,
        eventCount: 2,
        created_at: '2026-11-14T14:00:00Z',
        createdAt: '2026-11-14T14:00:00Z',
      };

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(backendReport), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const report = await reportsApi.generateReport(payload);

      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/reports/generate',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(payload),
        })
      );

      expect(report.shiftKey).toBe('2026-11-14-early');
      expect(report.modelUsed).toBe('google/gemini-3.5-flash-lite');
      expect(report.eventCount).toBe(2);
      expect(report.createdAt).toBe('2026-11-14T14:00:00Z');
      expect(report.openActions).toHaveLength(1);
      expect(report.openActions[0].action).toBe('Clean up oil spill near Conveyor-B');
      expect(report.openActions[0].priority).toBe('high');
      expect(report.safetyNotes).toEqual(['Oil spill cordoned off with cones']);
      expect((report as unknown as Record<string, unknown>).open_actions).toBeDefined();
      expect((report as unknown as Record<string, unknown>).safety_notes).toBeDefined();
    });

    it('generates report safely when backend returns pure snake_case response', async () => {
      const payload: ReportGenerateRequest = {
        shiftKey: '2026-11-14-night',
      };

      const backendSnakeReport = {
        id: '3cff7f41-1053-4548-a6f5-153fc558a04e',
        shift_key: '2026-11-14-night',
        version: 1,
        summary: 'Night shift routine summary.',
        open_actions: [
          {
            action: 'Check coolant temperature',
            owner: 'Maintenance',
            priority: 'medium',
          },
        ],
        safety_notes: ['No incidents logged'],
        model_used: 'google/gemini-3.1-flash-lite',
        event_count: 1,
        created_at: '2026-11-14T22:00:00Z',
      };

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(backendSnakeReport), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const report = await reportsApi.generateReport(payload);

      expect(report.shiftKey).toBe('2026-11-14-night');
      expect(report.modelUsed).toBe('google/gemini-3.1-flash-lite');
      expect(report.eventCount).toBe(1);
      expect(report.openActions).toHaveLength(1);
      expect(report.safetyNotes).toEqual(['No incidents logged']);
    });

    it('lists reports filtered by shiftKey and returns populated modelUsed and eventCount', async () => {
      const backendSummaries = [
        {
          id: '2cff7f41-1053-4548-a6f5-153fc558a04d',
          shift_key: '2026-11-14-early',
          shiftKey: '2026-11-14-early',
          version: 2,
          model_used: 'google/gemini-3.5-flash-lite',
          modelUsed: 'google/gemini-3.5-flash-lite',
          event_count: 3,
          eventCount: 3,
          created_at: '2026-11-14T14:30:00Z',
          createdAt: '2026-11-14T14:30:00Z',
        },
      ];

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(backendSummaries), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const summaries = await reportsApi.listReports('2026-11-14-early');

      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/reports?shiftKey=2026-11-14-early',
        expect.objectContaining({ method: 'GET' })
      );

      expect(summaries).toHaveLength(1);
      expect(summaries[0].shiftKey).toBe('2026-11-14-early');
      expect(summaries[0].modelUsed).toBe('google/gemini-3.5-flash-lite');
      expect(summaries[0].eventCount).toBe(3);
      expect(summaries[0].version).toBe(2);
      expect((summaries[0] as unknown as Record<string, unknown>).model_used).toBe('google/gemini-3.5-flash-lite');
      expect((summaries[0] as unknown as Record<string, unknown>).event_count).toBe(3);
    });
  });

  describe('adminApi direct compatibility', () => {
    it('updates active and fallback models with camelCase payload and returns updated models', async () => {
      const payload: AdminSettingsUpdate = {
        activeModel: 'google/gemini-3.5-pro',
        fallbackModel: 'google/gemini-3.5-flash',
      };

      const backendSettings = {
        active_model: 'google/gemini-3.5-pro',
        fallback_model: 'google/gemini-3.5-flash',
      };

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(backendSettings), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const updated = await adminApi.updateSettings(payload, 'admin-token-xyz');

      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/admin/settings',
        expect.objectContaining({
          method: 'PUT',
          headers: expect.any(Headers),
          body: JSON.stringify(payload),
        })
      );

      expect(updated.activeModel).toBe('google/gemini-3.5-pro');
      expect(updated.fallbackModel).toBe('google/gemini-3.5-flash');
      expect((updated as unknown as Record<string, unknown>).active_model).toBe('google/gemini-3.5-pro');
      expect((updated as unknown as Record<string, unknown>).fallback_model).toBe('google/gemini-3.5-flash');
    });

    it('retrieves settings with getSettings and returns accessible activeModel and fallbackModel', async () => {
      const backendSettings = {
        active_model: 'google/gemini-3.5-flash-lite',
        fallback_model: 'google/gemini-3.1-flash-lite',
      };

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(backendSettings), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const settings = await adminApi.getSettings('admin-token-xyz');

      expect(settings.activeModel).toBe('google/gemini-3.5-flash-lite');
      expect(settings.fallbackModel).toBe('google/gemini-3.1-flash-lite');
      expect((settings as unknown as Record<string, unknown>).active_model).toBe('google/gemini-3.5-flash-lite');
      expect((settings as unknown as Record<string, unknown>).fallback_model).toBe('google/gemini-3.1-flash-lite');
    });
  });
});
