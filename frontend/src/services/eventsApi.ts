import { apiClient, type RequestConfig } from './apiClient.ts';
import type {
  EventCreateRequest,
  EventResponse,
  ShiftKey,
} from '../types/api.ts';
import type { EventsService } from './types.ts';

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
 * Normalizes an event response object ensuring both camelCase and snake_case properties are present.
 */
export function normalizeEventResponse(data: unknown): EventResponse {
  if (!data || typeof data !== 'object') {
    return data as EventResponse;
  }
  const raw = data as Record<string, unknown>;
  const shiftKey = (raw.shiftKey ?? raw.shift_key ?? '') as ShiftKey;
  const createdAt = (raw.createdAt ?? raw.created_at ?? '') as string;

  const result: EventResponse = {
    ...(raw as unknown as EventResponse),
    shiftKey,
    createdAt,
  };

  ensureProperty(result, 'shift_key', raw.shift_key ?? shiftKey, 'shift_key' in raw);
  ensureProperty(result, 'created_at', raw.created_at ?? createdAt, 'created_at' in raw);

  return result;
}

export const eventsApi: EventsService = {
  /**
   * Records a new operational shift event.
   * POST /api/events
   */
  async createEvent(payload: EventCreateRequest, config?: RequestConfig): Promise<EventResponse> {
    const raw = await apiClient.post<EventResponse, EventCreateRequest>('/events', payload, config);
    return normalizeEventResponse(raw);
  },

  /**
   * Retrieves all logged events for a given shift key, sorted chronologically ascending.
   * GET /api/events?shiftKey=...
   */
  async listEvents(shiftKey: ShiftKey | string, config?: RequestConfig): Promise<EventResponse[]> {
    const list = await apiClient.get<EventResponse[]>('/events', {
      ...config,
      params: {
        ...config?.params,
        shiftKey,
      },
    });
    return Array.isArray(list) ? list.map(normalizeEventResponse) : [];
  },

  /**
   * Permanently deletes an event by its unique UUID.
   * DELETE /api/events/{id}
   */
  deleteEvent(id: string, config?: RequestConfig): Promise<void> {
    return apiClient.delete<void>(`/events/${encodeURIComponent(id)}`, config);
  },
};

export const realEventsApi = eventsApi;
export default eventsApi;
