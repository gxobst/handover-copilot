import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  apiClient,
  get,
  post,
  put,
  del,
  buildUrl,
  getBaseUrl,
} from './apiClient.ts';
import {
  ApiError,
  isApiError,
  toProblemDetails,
  extractTraceId,
  type ProblemDetails,
} from './errors.ts';
import { healthApi } from './healthApi.ts';
import { eventsApi } from './eventsApi.ts';
import { reportsApi } from './reportsApi.ts';
import { adminApi } from './adminApi.ts';
import type {
  EventCreateRequest,
  EventResponse,
  ReportGenerateRequest,
  ReportResponse,
  AdminSettingsUpdate,
  HealthResponse,
} from '../types/api.ts';

describe('apiClient and RFC 9457 Error Handling', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  describe('Base URL resolution and URL building', () => {
    it('defaults cleanly to /api if VITE_API_BASE_URL is unset or empty', () => {
      expect(getBaseUrl()).toBe('/api');
      expect(buildUrl('/events')).toBe('/api/events');
    });

    it('normalizes base URL trailing slashes and endpoint leading slashes (e.g. http://localhost:8000/ + /events -> http://localhost:8000/events)', () => {
      const url = buildUrl('/events', undefined, 'http://localhost:8000/');
      expect(url).toBe('http://localhost:8000/events');
    });

    it('handles endpoints without leading slashes and base URLs without trailing slashes', () => {
      expect(buildUrl('events', undefined, 'http://localhost:8000')).toBe('http://localhost:8000/events');
      expect(buildUrl('events', undefined, '/api/')).toBe('/api/events');
    });

    it('deduplicates /api when base URL ends with /api and endpoint starts with /api/', () => {
      expect(buildUrl('/api/events', undefined, '/api')).toBe('/api/events');
      expect(buildUrl('/api/events', undefined, 'http://localhost:8000/api')).toBe('http://localhost:8000/api/events');
    });

    it('leaves absolute URLs intact', () => {
      expect(buildUrl('https://other-service.com/healthz')).toBe('https://other-service.com/healthz');
    });

    it('automatically serializes object query parameters with proper URI encoding', () => {
      const url1 = buildUrl('/events', { shiftKey: '2026-11-14-early' });
      expect(url1).toBe('/api/events?shiftKey=2026-11-14-early');

      const url2 = buildUrl('/events', { shift_key: '2026-11-14-early' });
      expect(url2).toBe('/api/events?shift_key=2026-11-14-early');

      const url3 = buildUrl('/events', {
        note: 'oil & water: 50% / high',
        active: true,
        count: 42,
      });
      expect(url3).toBe('/api/events?note=oil%20%26%20water%3A%2050%25%20%2F%20high&active=true&count=42');
    });

    it('omits undefined and null query parameters', () => {
      const url = buildUrl('/reports', {
        shiftKey: '2026-11-14-early',
        limit: undefined,
        filter: null,
      });
      expect(url).toBe('/api/events'.replace('events', 'reports') + '?shiftKey=2026-11-14-early');
    });

    it('appends with & if endpoint already contains query parameters', () => {
      const url = buildUrl('/events?existing=1', { shiftKey: '2026-11-14-early' });
      expect(url).toBe('/api/events?existing=1&shiftKey=2026-11-14-early');
    });
  });

  describe('HTTP Client Convenience Methods & Headers', () => {
    it('executes GET requests and parses JSON response', async () => {
      const mockData = { status: 'ok', version: '0.1.0', environment: 'test' };
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockData), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const result = await apiClient.get<typeof mockData>('/healthz');
      expect(result).toEqual(mockData);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/healthz',
        expect.objectContaining({ method: 'GET' })
      );
    });

    it('executes POST requests, sets Content-Type: application/json, and serializes body', async () => {
      const payload = { shiftKey: '2026-11-14-early', machine: 'Press-01', category: 'downtime', note: 'test' };
      const responseData = { id: 'evt-123', ...payload, createdAt: '2026-11-14T08:00:00Z' };

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(responseData), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const result = await apiClient.post<typeof responseData, typeof payload>('/events', payload);
      expect(result).toEqual(responseData);

      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/events',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(payload),
        })
      );

      const callArgs = vi.mocked(globalThis.fetch).mock.calls[0];
      const headers = (callArgs[1] as RequestInit).headers as Headers;
      expect(headers.get('Content-Type')).toBe('application/json');
    });

    it('executes PUT requests with body and custom headers', async () => {
      const payload = { activeModel: 'google/gemini-3.5-flash-lite' };
      const responseData = { activeModel: 'google/gemini-3.5-flash-lite', fallbackModel: 'google/gemini-3.1-flash-lite' };

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(responseData), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const result = await apiClient.put<typeof responseData, typeof payload>('/admin/settings', payload, {
        headers: { 'X-Custom-Header': 'custom-val' },
      });

      expect(result).toEqual(responseData);
      const callArgs = vi.mocked(globalThis.fetch).mock.calls[0];
      const headers = (callArgs[1] as RequestInit).headers as Headers;
      expect(headers.get('X-Custom-Header')).toBe('custom-val');
      expect(headers.get('Content-Type')).toBe('application/json');
    });

    it('supports standalone function exports: get, post, put, del', async () => {
      globalThis.fetch = vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        )
      );

      await get('/test-get');
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/test-get', expect.objectContaining({ method: 'GET' }));

      await post('/test-post', { foo: 'bar' });
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/test-post', expect.objectContaining({ method: 'POST' }));

      await put('/test-put', { foo: 'bar' });
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/test-put', expect.objectContaining({ method: 'PUT' }));

      await del('/test-del');
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/test-del', expect.objectContaining({ method: 'DELETE' }));
    });

    it('supports bearer token authentication via token config', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ activeModel: 'm1', fallbackModel: 'm2' }), { status: 200 })
      );

      await apiClient.get('/admin/settings', { token: 'secret-token-123' });

      const callArgs = vi.mocked(globalThis.fetch).mock.calls[0];
      const headers = (callArgs[1] as RequestInit).headers as Headers;
      expect(headers.get('Authorization')).toBe('Bearer secret-token-123');
    });

    it('preserves explicitly provided Authorization header over token option', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), { status: 200 })
      );

      await apiClient.get('/admin/settings', {
        token: 'ignored-token',
        headers: { Authorization: 'Basic custom-credentials' },
      });

      const callArgs = vi.mocked(globalThis.fetch).mock.calls[0];
      const headers = (callArgs[1] as RequestInit).headers as Headers;
      expect(headers.get('Authorization')).toBe('Basic custom-credentials');
    });

    it('resolves HTTP 204 No Content without JSON parsing errors on empty bodies', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(null, {
          status: 204,
          statusText: 'No Content',
        })
      );

      const result = await apiClient.delete<void>('/events/41f34ec4-f489-4362-869d-9555cd9c0f98');
      expect(result).toBeUndefined();
    });
  });

  describe('RFC 9457 Problem Details Error Normalization', () => {
    it('parses application/problem+json 422 error into ApiError with populated ProblemDetails', async () => {
      const problemPayload: ProblemDetails = {
        type: 'https://example.com/probs/validation',
        title: 'Unprocessable Entity',
        status: 422,
        detail: 'Shift key format is invalid',
        traceId: 'trace-422-abc',
      };

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(problemPayload), {
          status: 422,
          statusText: 'Unprocessable Entity',
          headers: { 'Content-Type': 'application/problem+json' },
        })
      );

      try {
        await apiClient.get('/events', { params: { shiftKey: 'invalid' } });
        expect.fail('Should have thrown an ApiError');
      } catch (err: unknown) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.status).toBe(422);
          expect(err.statusText).toBe('Unprocessable Entity');
          expect(err.problemDetails.title).toBe('Unprocessable Entity');
          expect(err.problemDetails.detail).toBe('Shift key format is invalid');
          expect(err.problemDetails.type).toBe('https://example.com/probs/validation');
          expect(err.problemDetails.traceId).toBe('trace-422-abc');
        }
      }
    });

    it('extracts traceId from body.traceId (priority 1)', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            title: 'Bad Request',
            status: 400,
            detail: 'Missing required field',
            traceId: 'primary-trace-id',
            trace_id: 'secondary-trace-id',
          }),
          {
            status: 400,
            headers: {
              'Content-Type': 'application/json',
              'X-Trace-ID': 'header-trace-id',
            },
          }
        )
      );

      try {
        await apiClient.post('/events', {});
        expect.fail('Expected error');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.problemDetails.traceId).toBe('primary-trace-id');
          expect(extractTraceId(err)).toBe('primary-trace-id');
        }
      }
    });

    it('extracts traceId from body.trace_id when body.traceId is missing (priority 2)', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            title: 'Bad Request',
            status: 400,
            detail: 'Missing required field',
            trace_id: 'snake-case-trace-id',
          }),
          {
            status: 400,
            headers: {
              'Content-Type': 'application/json',
              'X-Trace-ID': 'header-trace-id',
            },
          }
        )
      );

      try {
        await apiClient.post('/events', {});
        expect.fail('Expected error');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.problemDetails.traceId).toBe('snake-case-trace-id');
          expect(extractTraceId(err)).toBe('snake-case-trace-id');
        }
      }
    });

    it('falls back to X-Trace-ID or x-trace-id HTTP response header when body has no traceId (priority 3)', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            title: 'Internal Server Error',
            status: 500,
            detail: 'Database connection failed',
          }),
          {
            status: 500,
            headers: {
              'Content-Type': 'application/json',
              'X-Trace-ID': 'header-trace-999',
            },
          }
        )
      );

      try {
        await apiClient.get('/events');
        expect.fail('Expected error');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.problemDetails.traceId).toBe('header-trace-999');
          expect(extractTraceId(err)).toBe('header-trace-999');
        }
      }
    });

    it('synthesizes upstream HTML / non-JSON error responses (e.g. gateway 502/503/504) into valid ApiError', async () => {
      const htmlBody = `<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center><hr><center>cloudflare / nginx</center></body></html>`;

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(htmlBody, {
          status: 502,
          statusText: 'Bad Gateway',
          headers: {
            'Content-Type': 'text/html',
            'x-trace-id': 'proxy-trace-502',
          },
        })
      );

      try {
        await apiClient.get('/healthz');
        expect.fail('Expected error');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.status).toBe(502);
          expect(err.statusText).toBe('Bad Gateway');
          expect(err.problemDetails.status).toBe(502);
          expect(err.problemDetails.title).toBe('Bad Gateway');
          expect(err.problemDetails.detail).toBe(htmlBody);
          expect(err.problemDetails.traceId).toBe('proxy-trace-502');
          expect(err.problemDetails.type).toBe('about:blank');
        }
      }
    });

    it('truncates non-JSON error bodies exceeding 300 characters', async () => {
      const longBody = 'A'.repeat(500);

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(longBody, {
          status: 504,
          statusText: 'Gateway Timeout',
          headers: { 'Content-Type': 'text/plain' },
        })
      );

      try {
        await apiClient.get('/reports/generate');
        expect.fail('Expected error');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.status).toBe(504);
          expect(err.problemDetails.detail.length).toBe(300);
          expect(err.problemDetails.detail).toBe('A'.repeat(300));
        }
      }
    });

    it('normalizes empty error response bodies with standard fallback title and detail', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response('', {
          status: 500,
          statusText: 'Internal Server Error',
        })
      );

      try {
        await apiClient.get('/events');
        expect.fail('Expected error');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.status).toBe(500);
          expect(err.problemDetails.title).toBe('Internal Server Error');
          expect(err.problemDetails.detail).toBe('An unexpected internal server error occurred.');
          expect(err.problemDetails.type).toBe('about:blank');
        }
      }
    });

    it('normalizes network disconnects and TypeError: Failed to fetch into status: 0 Network Error', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));

      try {
        await apiClient.get('/healthz');
        expect.fail('Expected error');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.status).toBe(0);
          expect(err.problemDetails.status).toBe(0);
          expect(err.problemDetails.title).toBe('Network Error');
          expect(err.problemDetails.detail).toBe(
            'Unable to connect to the server. Please check your network connection.'
          );
        }
      }
    });

    it('normalizes request cancellations via AbortSignal into Request Aborted', async () => {
      const abortError = new DOMException('The user aborted a request.', 'AbortError');
      globalThis.fetch = vi.fn().mockRejectedValue(abortError);

      try {
        const controller = new AbortController();
        controller.abort();
        await apiClient.get('/reports', { signal: controller.signal });
        expect.fail('Expected error');
      } catch (err) {
        expect(isApiError(err)).toBe(true);
        if (isApiError(err)) {
          expect(err.status).toBe(0);
          expect(err.problemDetails.title).toBe('Request Aborted');
          expect(err.problemDetails.status).toBe(0);
        }
      }
    });
  });

  describe('Error Utilities: isApiError, toProblemDetails, extractTraceId', () => {
    it('isApiError accurately identifies ApiError instances', () => {
      const apiErr = new ApiError(404, 'Not Found', {
        type: 'about:blank',
        title: 'Not Found',
        status: 404,
        detail: 'Event not found',
      });
      expect(isApiError(apiErr)).toBe(true);
      expect(isApiError(new Error('Standard Error'))).toBe(false);
      expect(isApiError('Error string')).toBe(false);
      expect(isApiError(null)).toBe(false);
      expect(isApiError(undefined)).toBe(false);
      expect(isApiError({})).toBe(false);
    });

    it('toProblemDetails returns problemDetails from ApiError', () => {
      const pd: ProblemDetails = {
        type: 'about:blank',
        title: 'Forbidden',
        status: 403,
        detail: 'Access denied',
        traceId: 'tr-403',
      };
      const apiErr = new ApiError(403, 'Forbidden', pd);
      expect(toProblemDetails(apiErr)).toEqual(pd);
    });

    it('toProblemDetails converts native Error into structured ProblemDetails', () => {
      const nativeErr = new Error('Database connection timeout');
      const pd = toProblemDetails(nativeErr);
      expect(pd.status).toBe(500);
      expect(pd.title).toBe('Error');
      expect(pd.detail).toBe('Database connection timeout');
      expect(pd.type).toBe('about:blank');
    });

    it('toProblemDetails converts AbortError into structured ProblemDetails', () => {
      const abortErr = new DOMException('Aborted operation', 'AbortError');
      const pd = toProblemDetails(abortErr);
      expect(pd.status).toBe(0);
      expect(pd.title).toBe('Request Aborted');
      expect(pd.detail).toBe('Aborted operation');
    });

    it('toProblemDetails converts string and unknown types safely', () => {
      const pdString = toProblemDetails('Something broke unexpectedly');
      expect(pdString.status).toBe(500);
      expect(pdString.title).toBe('Error');
      expect(pdString.detail).toBe('Something broke unexpectedly');

      const pdUnknown = toProblemDetails(null);
      expect(pdUnknown.status).toBe(500);
      expect(pdUnknown.title).toBe('Unexpected Error');
    });

    it('extractTraceId resolves trace ID from different error formats', () => {
      expect(extractTraceId(null)).toBeUndefined();
      expect(extractTraceId('error')).toBeUndefined();
      expect(extractTraceId({ traceId: 'tr-1' })).toBe('tr-1');
      expect(extractTraceId({ trace_id: 'tr-2' })).toBe('tr-2');
      expect(extractTraceId({ problemDetails: { traceId: 'tr-3' } })).toBe('tr-3');
      expect(extractTraceId({ problemDetails: { trace_id: 'tr-4' } })).toBe('tr-4');

      const apiErr = new ApiError(500, 'Server Error', {
        type: 'about:blank',
        title: 'Server Error',
        status: 500,
        detail: 'Error',
        traceId: 'tr-5',
      });
      expect(extractTraceId(apiErr)).toBe('tr-5');
    });
  });

  describe('Domain API Services Implementation', () => {
    it('healthApi.getHealth calls GET /api/healthz and returns HealthResponse', async () => {
      const mockResponse: HealthResponse = {
        status: 'ok',
        version: '0.1.0',
        environment: 'local',
      };
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockResponse), { status: 200 })
      );

      const health = await healthApi.getHealth();
      expect(health).toEqual(mockResponse);
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/healthz', expect.objectContaining({ method: 'GET' }));
    });

    it('eventsApi.createEvent calls POST /api/events with payload and returns EventResponse', async () => {
      const payload: EventCreateRequest = {
        shiftKey: '2026-11-14-early',
        machine: 'Press-01',
        category: 'downtime',
        note: 'Hydraulic pressure dropped suddenly',
      };
      const mockResponse: EventResponse = {
        id: '41f34ec4-f489-4362-869d-9555cd9c0f98',
        shiftKey: '2026-11-14-early',
        machine: 'Press-01',
        category: 'downtime',
        note: 'Hydraulic pressure dropped suddenly',
        createdAt: '2026-11-14T06:45:00Z',
      };

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockResponse), { status: 201 })
      );

      const created = await eventsApi.createEvent(payload);
      expect(created).toEqual(mockResponse);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/events',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(payload),
        })
      );
    });

    it('eventsApi.listEvents calls GET /api/events with shiftKey query param', async () => {
      const mockEvents: EventResponse[] = [
        {
          id: 'evt-1',
          shiftKey: '2026-11-14-early',
          machine: 'Press-01',
          category: 'safety',
          note: 'Oil spill cordoned off',
          createdAt: '2026-11-14T07:00:00Z',
        },
      ];

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockEvents), { status: 200 })
      );

      const events = await eventsApi.listEvents('2026-11-14-early');
      expect(events).toEqual(mockEvents);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/events?shiftKey=2026-11-14-early',
        expect.objectContaining({ method: 'GET' })
      );
    });

    it('eventsApi.deleteEvent calls DELETE /api/events/{id} and returns void', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(null, { status: 204 })
      );

      const result = await eventsApi.deleteEvent('41f34ec4-f489-4362-869d-9555cd9c0f98');
      expect(result).toBeUndefined();
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/events/41f34ec4-f489-4362-869d-9555cd9c0f98',
        expect.objectContaining({ method: 'DELETE' })
      );
    });

    it('reportsApi.generateReport calls POST /api/reports/generate with payload', async () => {
      const payload: ReportGenerateRequest = { shiftKey: '2026-11-14-early' };
      const mockReport: ReportResponse = {
        id: '2cff7f41-1053-4548-a6f5-153fc558a04d',
        shiftKey: '2026-11-14-early',
        version: 1,
        summary: 'All stations operated smoothly.',
        openActions: [
          {
            action: 'Wipe conveyor oil leak',
            owner: 'Shift lead',
            priority: 'high',
          },
        ],
        safetyNotes: ['Oil spill near Conveyor-B'],
        modelUsed: 'google/gemini-3.5-flash-lite',
        eventCount: 1,
        createdAt: '2026-11-14T14:00:00Z',
      };

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockReport), { status: 201 })
      );

      const report = await reportsApi.generateReport(payload);
      expect(report).toEqual(mockReport);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/reports/generate',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(payload),
        })
      );
    });

    it('reportsApi.listReports calls GET /api/reports with optional shiftKey', async () => {
      const mockSummaries = [
        {
          id: '2cff7f41-1053-4548-a6f5-153fc558a04d',
          shiftKey: '2026-11-14-early',
          version: 1,
          modelUsed: 'google/gemini-3.5-flash-lite',
          eventCount: 2,
          createdAt: '2026-11-14T14:00:00Z',
        },
      ];

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockSummaries), { status: 200 })
      );

      const summaries = await reportsApi.listReports('2026-11-14-early');
      expect(summaries).toEqual(mockSummaries);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/reports?shiftKey=2026-11-14-early',
        expect.objectContaining({ method: 'GET' })
      );
    });

    it('reportsApi.getReport calls GET /api/reports/{id}', async () => {
      const mockReport: ReportResponse = {
        id: '2cff7f41-1053-4548-a6f5-153fc558a04d',
        shiftKey: '2026-11-14-early',
        version: 1,
        summary: 'Report summary',
        openActions: [],
        safetyNotes: [],
        modelUsed: 'google/gemini-3.5-flash-lite',
        eventCount: 0,
        createdAt: '2026-11-14T14:00:00Z',
      };

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockReport), { status: 200 })
      );

      const report = await reportsApi.getReport('2cff7f41-1053-4548-a6f5-153fc558a04d');
      expect(report).toEqual(mockReport);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/reports/2cff7f41-1053-4548-a6f5-153fc558a04d',
        expect.objectContaining({ method: 'GET' })
      );
    });

    it('adminApi.getSettings calls GET /api/admin/settings with token', async () => {
      const mockSettings = {
        activeModel: 'google/gemini-3.5-flash-lite',
        fallbackModel: 'google/gemini-3.1-flash-lite',
      };

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockSettings), { status: 200 })
      );

      const settings = await adminApi.getSettings('admin-secret-token');
      expect(settings).toEqual(mockSettings);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/admin/settings',
        expect.objectContaining({
          method: 'GET',
        })
      );
      const callArgs = vi.mocked(globalThis.fetch).mock.calls[0];
      const headers = (callArgs[1] as RequestInit).headers as Headers;
      expect(headers.get('Authorization')).toBe('Bearer admin-secret-token');
    });

    it('adminApi.updateSettings calls PUT /api/admin/settings with payload and token', async () => {
      const updatePayload: AdminSettingsUpdate = {
        activeModel: 'google/gemini-3.5-pro',
      };
      const mockResponse = {
        activeModel: 'google/gemini-3.5-pro',
        fallbackModel: 'google/gemini-3.1-flash-lite',
      };

      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockResponse), { status: 200 })
      );

      const updated = await adminApi.updateSettings(updatePayload, 'admin-secret-token');
      expect(updated).toEqual(mockResponse);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/admin/settings',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify(updatePayload),
        })
      );
      const callArgs = vi.mocked(globalThis.fetch).mock.calls[0];
      const headers = (callArgs[1] as RequestInit).headers as Headers;
      expect(headers.get('Authorization')).toBe('Bearer admin-secret-token');
      expect(headers.get('Content-Type')).toBe('application/json');
    });
  });
});
