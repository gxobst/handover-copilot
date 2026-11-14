import { apiClient, type RequestConfig } from './apiClient.ts';
import type {
  EventCreateRequest,
  EventResponse,
  ShiftKey,
} from '../types/api.ts';

export const eventsApi = {
  /**
   * Records a new operational shift event.
   * POST /api/events
   */
  createEvent(payload: EventCreateRequest, config?: RequestConfig): Promise<EventResponse> {
    return apiClient.post<EventResponse, EventCreateRequest>('/events', payload, config);
  },

  /**
   * Retrieves all logged events for a given shift key, sorted chronologically ascending.
   * GET /api/events?shiftKey=...
   */
  listEvents(shiftKey: ShiftKey | string, config?: RequestConfig): Promise<EventResponse[]> {
    return apiClient.get<EventResponse[]>('/events', {
      ...config,
      params: {
        ...config?.params,
        shiftKey,
      },
    });
  },

  /**
   * Permanently deletes an event by its unique UUID.
   * DELETE /api/events/{id}
   */
  deleteEvent(id: string, config?: RequestConfig): Promise<void> {
    return apiClient.delete<void>(`/events/${encodeURIComponent(id)}`, config);
  },
};

export default eventsApi;
