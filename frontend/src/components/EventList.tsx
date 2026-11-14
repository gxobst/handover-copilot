import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  Clock,
  Trash2,
  Filter,
  AlertCircle,
  RefreshCw,
  Inbox,
  Loader2,
} from 'lucide-react';
import type { Category, EventResponse } from '../types';
import {
  eventsApi,
  type ApiError,
  toProblemDetails,
  extractTraceId,
  isApiError,
} from '../services';
import { isValidShiftKey } from '../utils/shiftKey';

export interface EventListProps {
  /** Current active shift identifier (e.g. "2026-11-14-early") */
  shiftKey: string;
  /** Optional callback triggered when an event is deleted */
  onEventDeleted?: (eventId: string) => void;
  /** Optional callback triggered on fetch or delete failure */
  onError?: (error: Error | ApiError) => void;
  /** Optional prop to disable interactive buttons like delete */
  disabled?: boolean;
  /** Optional prop to trigger list refetch when new events are logged */
  refreshKey?: number | string;
  /** Optional container styling */
  className?: string;
}

export type FilterCategory = 'all' | Category;

interface FilterOption {
  value: FilterCategory;
  label: string;
}

const FILTER_OPTIONS: readonly FilterOption[] = [
  { value: 'all', label: 'All' },
  { value: 'downtime', label: 'Downtime' },
  { value: 'quality', label: 'Quality' },
  { value: 'safety', label: 'Safety' },
  { value: 'info', label: 'Info' },
];

const CATEGORY_BADGE_CLASSES: Record<Category, string> = {
  downtime: 'bg-amber-100 text-amber-800 border-amber-300',
  quality: 'bg-purple-100 text-purple-800 border-purple-300',
  safety: 'bg-red-100 text-red-800 border-red-300 font-semibold',
  info: 'bg-slate-100 text-slate-800 border-slate-300',
};

/**
 * Formats ISO timestamp string to local plant date & time "YYYY-MM-DD HH:mm".
 */
function formatEventTimestamp(isoString: string): string {
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
  } catch {
    return isoString;
  }
}

interface ApiErrorDetails {
  detail: string;
  traceId?: string;
}

export const EventList: React.FC<EventListProps> = ({
  shiftKey,
  onEventDeleted,
  onError,
  disabled = false,
  refreshKey,
  className = '',
}) => {
  // Shift key validation
  const isShiftValid = Boolean(shiftKey && isValidShiftKey(shiftKey));

  const [events, setEvents] = useState<EventResponse[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<FilterCategory>('all');
  const [isLoading, setIsLoading] = useState<boolean>(() => isShiftValid);
  const [isColdStarting, setIsColdStarting] = useState(false);
  const [fetchError, setFetchError] = useState<ApiErrorDetails | null>(null);

  // Deletion states
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingEventId, setDeletingEventId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<ApiErrorDetails | null>(null);

  // Manual retry trigger nonce
  const [retryNonce, setRetryNonce] = useState(0);

  const coldStartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset deletion states and set loading on shift change or refetch during render
  const [prevShiftKey, setPrevShiftKey] = useState(shiftKey);
  const [prevRefreshKey, setPrevRefreshKey] = useState(refreshKey);
  if (shiftKey !== prevShiftKey || refreshKey !== prevRefreshKey) {
    setPrevShiftKey(shiftKey);
    setPrevRefreshKey(refreshKey);
    setConfirmDeleteId(null);
    setDeletingEventId(null);
    setDeleteError(null);
    setIsLoading(isShiftValid);
    if (!isShiftValid) {
      setEvents([]);
      setFetchError(null);
    }
  }

  // Clear timers on unmount
  useEffect(() => {
    return () => {
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current);
      }
    };
  }, []);

  // Fetch events when shiftKey, refreshKey, or retryNonce changes
  useEffect(() => {
    if (!isShiftValid) {
      return;
    }

    let isCurrent = true;

    if (coldStartTimerRef.current) {
      clearTimeout(coldStartTimerRef.current);
      coldStartTimerRef.current = null;
    }

    coldStartTimerRef.current = setTimeout(() => {
      if (isCurrent) {
        setIsColdStarting(true);
      }
    }, 3000);

    eventsApi
      .listEvents(shiftKey)
      .then((data) => {
        if (!isCurrent) return;
        setEvents(data);
        setIsLoading(false);
        setIsColdStarting(false);
        if (coldStartTimerRef.current) {
          clearTimeout(coldStartTimerRef.current);
          coldStartTimerRef.current = null;
        }
      })
      .catch((err: unknown) => {
        if (!isCurrent) return;
        const pd = toProblemDetails(err);
        const traceId = extractTraceId(err);
        setFetchError({ detail: pd.detail, traceId });
        setIsLoading(false);
        setIsColdStarting(false);
        if (coldStartTimerRef.current) {
          clearTimeout(coldStartTimerRef.current);
          coldStartTimerRef.current = null;
        }
        if (onError) {
          onError(err instanceof Error || isApiError(err) ? err : new Error(pd.detail));
        }
      });

    return () => {
      isCurrent = false;
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current);
        coldStartTimerRef.current = null;
      }
    };
  }, [shiftKey, refreshKey, retryNonce, isShiftValid, onError]);

  // Handle Retry
  const handleRetry = useCallback(() => {
    setIsLoading(true);
    setFetchError(null);
    setRetryNonce((prev) => prev + 1);
  }, []);

  // Handle Delete Confirmation
  const handleConfirmDelete = async (eventId: string) => {
    if (disabled || deletingEventId) return;

    setDeletingEventId(eventId);
    setDeleteError(null);

    try {
      await eventsApi.deleteEvent(eventId);
      setEvents((prev) => prev.filter((e) => e.id !== eventId));
      setConfirmDeleteId(null);
      if (onEventDeleted) {
        onEventDeleted(eventId);
      }
    } catch (err: unknown) {
      const pd = toProblemDetails(err);
      const traceId = extractTraceId(err);
      setDeleteError({
        detail: pd.detail,
        traceId,
      });
      setConfirmDeleteId(null);
      if (onError) {
        onError(err instanceof Error || isApiError(err) ? err : new Error(pd.detail));
      }
    } finally {
      setDeletingEventId(null);
    }
  };

  // Chronologically sorted events (ascending by createdAt: earliest first)
  const sortedEvents = useMemo(() => {
    return [...events].sort((a, b) => {
      const timeA = new Date(a.createdAt).getTime();
      const timeB = new Date(b.createdAt).getTime();
      return timeA - timeB;
    });
  }, [events]);

  // Dynamic counts for each filter category
  const categoryCounts = useMemo(() => {
    const counts: Record<FilterCategory, number> = {
      all: events.length,
      downtime: 0,
      quality: 0,
      safety: 0,
      info: 0,
    };
    for (const ev of events) {
      if (ev.category in counts) {
        counts[ev.category as Category]++;
      }
    }
    return counts;
  }, [events]);

  // Filtered list based on selected category
  const displayedEvents = useMemo(() => {
    if (selectedCategory === 'all') {
      return sortedEvents;
    }
    return sortedEvents.filter((ev) => ev.category === selectedCategory);
  }, [sortedEvents, selectedCategory]);

  // If shiftKey is empty or invalid, render guidance prompt and suppress API
  if (!isShiftValid) {
    return (
      <div className={`space-y-4 ${className}`.trim()}>
        <div
          role="status"
          aria-live="polite"
          className="flex flex-col items-center justify-center p-8 text-center bg-slate-50 border border-dashed border-slate-300 rounded-lg text-slate-500"
        >
          <Inbox className="w-10 h-10 text-slate-400 mb-2" aria-hidden="true" />
          <p className="text-sm font-medium">Select a valid shift to view events.</p>
        </div>
      </div>
    );
  }

  const isDeletingAny = Boolean(deletingEventId);

  return (
    <div className={`space-y-4 ${className}`.trim()}>
      {/* Category Filter Bar */}
      <div
        role="toolbar"
        aria-label="Category filters"
        className="flex flex-wrap items-center gap-2"
      >
        {FILTER_OPTIONS.map((opt) => {
          const isSelected = selectedCategory === opt.value;
          const count = categoryCounts[opt.value];
          return (
            <button
              key={opt.value}
              type="button"
              role="button"
              aria-label={`${opt.label} (${count})`}
              aria-pressed={isSelected}
              disabled={disabled || isLoading}
              onClick={() => setSelectedCategory(opt.value)}
              className={`inline-flex items-center px-3 py-1.5 text-xs font-semibold rounded-full border transition-colors focus:outline-none focus:ring-2 focus:ring-slate-900 ${
                isSelected
                  ? 'bg-slate-900 text-white border-slate-900 shadow-sm'
                  : 'bg-white text-slate-700 hover:bg-slate-100 border-slate-300'
              } ${disabled || isLoading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              <span>{opt.label}</span>
              <span
                className={`ml-1.5 px-1.5 py-0.2 rounded-full text-[11px] font-mono ${
                  isSelected ? 'bg-slate-800 text-slate-100' : 'bg-slate-100 text-slate-600'
                }`}
              >
                ({count})
              </span>
            </button>
          );
        })}
      </div>

      {/* Cold-start Alert (>3s In-Flight) */}
      {isColdStarting && (
        <div
          role="alert"
          aria-live="polite"
          className="flex items-center gap-2 p-3 text-sm rounded-md bg-amber-50 border border-amber-300 text-amber-900"
        >
          <Clock className="w-4 h-4 text-amber-700 flex-shrink-0 animate-pulse" aria-hidden="true" />
          <span>
            Waking up the database — the first request after an idle period may take up to 20 s.
          </span>
        </div>
      )}

      {/* Deletion Failure Banner */}
      {deleteError && (
        <div
          role="alert"
          aria-live="polite"
          className="flex items-center justify-between p-3 rounded-md bg-red-50 border border-red-300 text-red-900"
        >
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2 font-medium text-sm">
              <AlertCircle className="w-4 h-4 text-red-700 flex-shrink-0" aria-hidden="true" />
              <span>{deleteError.detail}</span>
            </div>
            {deleteError.traceId && (
              <span className="text-xs text-red-700 font-mono pl-6">
                Trace ID: {deleteError.traceId}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => setDeleteError(null)}
            className="text-xs font-semibold text-red-700 hover:text-red-900 px-2 py-1 rounded"
            aria-label="Dismiss error"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Main Content Area: Error, Loading Skeletons, Empty States, or Table */}
      {fetchError ? (
        /* Error State with Retry Button */
        <div
          role="alert"
          aria-live="polite"
          className="flex flex-col items-center justify-center p-8 text-center bg-red-50 border border-red-300 rounded-lg text-red-900 space-y-3"
        >
          <AlertCircle className="w-8 h-8 text-red-600" aria-hidden="true" />
          <div>
            <h3 className="text-base font-semibold text-red-900">Failed to load shift events</h3>
            <p className="text-sm text-red-700 mt-1">{fetchError.detail}</p>
            {fetchError.traceId && (
              <p className="text-xs font-mono text-red-600 mt-1">Trace ID: {fetchError.traceId}</p>
            )}
          </div>
          <button
            type="button"
            disabled={disabled || isLoading}
            onClick={handleRetry}
            className="inline-flex items-center px-4 py-2 text-sm font-semibold rounded-md shadow-sm bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-red-500"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} aria-hidden="true" />
            Retry
          </button>
        </div>
      ) : isLoading ? (
        /* Loading Skeleton Table */
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          aria-label="Loading events..."
          className="overflow-x-auto border border-slate-200 rounded-lg shadow-sm bg-white"
        >
          <table className="min-w-full divide-y divide-slate-200 text-left">
            <thead className="bg-slate-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider w-36">
                  Time
                </th>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider w-40">
                  Machine
                </th>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider w-28">
                  Category
                </th>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Note
                </th>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider text-right w-24">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody data-testid="event-list-loading" className="divide-y divide-slate-200 bg-white">
              {[1, 2, 3].map((rowIdx) => (
                <tr key={rowIdx} className="animate-pulse" data-testid="event-skeleton">
                  <td className="px-4 py-3">
                    <div className="h-4 bg-slate-200 rounded w-28" />
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-4 bg-slate-200 rounded w-24" />
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-5 bg-slate-200 rounded-full w-20" />
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-4 bg-slate-200 rounded w-5/6" />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="h-7 bg-slate-200 rounded w-8 ml-auto" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : events.length === 0 ? (
        /* Empty State: No Shift Events */
        <div
          role="status"
          className="flex flex-col items-center justify-center p-8 text-center bg-slate-50 border border-slate-200 rounded-lg text-slate-600"
        >
          <Inbox className="w-10 h-10 text-slate-400 mb-2" aria-hidden="true" />
          <h3 className="text-base font-semibold text-slate-800">No events logged for this shift</h3>
          <p className="text-sm text-slate-500 mt-1 max-w-md">
            Use the form above to log machine downtime, quality notes, safety incidents, or shift observations.
          </p>
        </div>
      ) : displayedEvents.length === 0 ? (
        /* Empty State: Filtered Category has 0 events */
        <div
          role="status"
          className="flex flex-col items-center justify-center p-8 text-center bg-slate-50 border border-slate-200 rounded-lg text-slate-600"
        >
          <Filter className="w-10 h-10 text-slate-400 mb-2" aria-hidden="true" />
          <p className="text-sm font-medium text-slate-700">
            No {selectedCategory} events recorded for this shift.
          </p>
          <button
            type="button"
            disabled={disabled}
            onClick={() => setSelectedCategory('all')}
            className="mt-3 inline-flex items-center px-3 py-1.5 text-xs font-semibold rounded-md bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-900"
          >
            Show all events
          </button>
        </div>
      ) : (
        /* Semantic Event Table */
        <div className="overflow-x-auto border border-slate-200 rounded-lg shadow-sm bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-left" aria-label="Shift events">
            <thead className="bg-slate-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider w-36">
                  Time
                </th>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider w-40">
                  Machine
                </th>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider w-28">
                  Category
                </th>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Note
                </th>
                <th scope="col" className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider text-right w-28">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {displayedEvents.map((event) => {
                const isThisConfirming = confirmDeleteId === event.id;
                const isThisDeleting = deletingEventId === event.id;
                const badgeClass = CATEGORY_BADGE_CLASSES[event.category] || CATEGORY_BADGE_CLASSES.info;

                return (
                  <tr key={event.id} className="hover:bg-slate-50/70 transition-colors">
                    {/* Timestamp */}
                    <td className="px-4 py-3 align-top text-xs text-slate-500 font-mono whitespace-nowrap">
                      <time dateTime={event.createdAt}>
                        {formatEventTimestamp(event.createdAt)}
                      </time>
                    </td>

                    {/* Machine */}
                    <td className="px-4 py-3 align-top text-sm font-semibold text-slate-900 break-words whitespace-normal">
                      {event.machine}
                    </td>

                    {/* Category Badge */}
                    <td className="px-4 py-3 align-top whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border capitalize ${badgeClass}`}
                      >
                        {event.category}
                      </span>
                    </td>

                    {/* Note: Strictly Escaped Text, preserving line breaks */}
                    <td className="px-4 py-3 align-top text-sm text-slate-800 break-words whitespace-pre-wrap">
                      {event.note}
                    </td>

                    {/* Action: Delete / Confirmation */}
                    <td className="px-4 py-3 align-top text-right whitespace-nowrap">
                      {isThisConfirming || isThisDeleting ? (
                        <div
                          className="inline-flex items-center gap-1.5"
                          role="group"
                          aria-label={`Confirm deletion for ${event.machine}`}
                        >
                          <span className="text-xs text-red-700 font-medium hidden sm:inline">Delete?</span>
                          <button
                            type="button"
                            disabled={disabled || isDeletingAny}
                            onClick={() => handleConfirmDelete(event.id)}
                            aria-label={`Confirm delete for ${event.machine}`}
                            className="inline-flex items-center px-2 py-1 text-xs font-semibold rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 cursor-pointer disabled:cursor-not-allowed"
                          >
                            {isThisDeleting ? (
                              <>
                                <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" aria-hidden="true" />
                                <span>Deleting...</span>
                              </>
                            ) : (
                              'Confirm'
                            )}
                          </button>
                          <button
                            type="button"
                            disabled={disabled || isDeletingAny}
                            onClick={() => setConfirmDeleteId(null)}
                            aria-label={`Cancel delete for ${event.machine}`}
                            className="px-2 py-1 text-xs font-semibold rounded bg-slate-200 text-slate-700 hover:bg-slate-300 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-400 cursor-pointer disabled:cursor-not-allowed"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          disabled={disabled || isLoading || isDeletingAny}
                          onClick={() => {
                            setDeleteError(null);
                            setConfirmDeleteId(event.id);
                          }}
                          aria-label={`Delete event for ${event.machine}`}
                          className="p-1.5 text-slate-400 hover:text-red-600 rounded hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 cursor-pointer"
                        >
                          <Trash2 className="w-4 h-4" aria-hidden="true" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default EventList;
