import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EventList } from './EventList';
import { eventsApi } from '../services';
import { ApiError } from '../services/errors';
import type { EventResponse } from '../types';

function formatEventTimestamp(isoString: string): string {
  const d = new Date(isoString);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hours = String(d.getHours()).padStart(2, '0');
  const minutes = String(d.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

describe('EventList Component', () => {
  const validShiftKey = '2026-11-14-early';

  const mockEvents: EventResponse[] = [
    {
      id: '11111111-1111-1111-1111-111111111111',
      shiftKey: validShiftKey,
      machine: 'Press-01',
      category: 'downtime',
      note: 'Hydraulic pressure dropped suddenly, line stopped for 45 minutes.',
      createdAt: '2026-11-14T06:30:00Z',
    },
    {
      id: '22222222-2222-2222-2222-222222222222',
      shiftKey: validShiftKey,
      machine: 'Conveyor-B',
      category: 'quality',
      note: 'Scratch defect on sheet surface.',
      createdAt: '2026-11-14T07:15:00Z',
    },
    {
      id: '33333333-3333-3333-3333-333333333333',
      shiftKey: validShiftKey,
      machine: 'Welder-04',
      category: 'safety',
      note: 'Guard switch failed open during operation.',
      createdAt: '2026-11-14T08:00:00Z',
    },
    {
      id: '44444444-4444-4444-4444-444444444444',
      shiftKey: validShiftKey,
      machine: 'Packaging-01',
      category: 'info',
      note: 'Mid-shift cleaning and grease check complete.',
      createdAt: '2026-11-14T09:30:00Z',
    },
  ];

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  describe('ShiftKey Validation & Fetch Suppression', () => {
    it('suppresses API call and renders prompt when shiftKey is empty', () => {
      const listSpy = vi.spyOn(eventsApi, 'listEvents');
      render(<EventList shiftKey="" />);

      expect(listSpy).not.toHaveBeenCalled();
      expect(screen.getByText(/select a valid shift to view events\./i)).toBeInTheDocument();
    });

    it('suppresses API call and renders prompt when shiftKey is invalid format', () => {
      const listSpy = vi.spyOn(eventsApi, 'listEvents');
      render(<EventList shiftKey="invalid-shift-format" />);

      expect(listSpy).not.toHaveBeenCalled();
      expect(screen.getByText(/select a valid shift to view events\./i)).toBeInTheDocument();
    });

    it('suppresses API call when shiftKey has invalid calendar date', () => {
      const listSpy = vi.spyOn(eventsApi, 'listEvents');
      render(<EventList shiftKey="2026-02-31-early" />);

      expect(listSpy).not.toHaveBeenCalled();
      expect(screen.getByText(/select a valid shift to view events\./i)).toBeInTheDocument();
    });

    it('automatically invokes eventsApi.listEvents when valid shiftKey is provided', async () => {
      const listSpy = vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(mockEvents);
      render(<EventList shiftKey={validShiftKey} />);

      expect(listSpy).toHaveBeenCalledTimes(1);
      expect(listSpy).toHaveBeenCalledWith(validShiftKey);
      expect(await screen.findByText('Press-01')).toBeInTheDocument();
    });
  });

  describe('Loading State & Skeleton Rendering', () => {
    it('displays skeleton table rows while request is in-flight and disables filter buttons', async () => {
      let resolvePromise: (value: EventResponse[]) => void = () => {};
      const pendingPromise = new Promise<EventResponse[]>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(eventsApi, 'listEvents').mockReturnValue(pendingPromise);

      render(<EventList shiftKey={validShiftKey} />);

      // Skeletons are rendered
      expect(screen.getByTestId('event-list-loading')).toBeInTheDocument();
      const skeletons = screen.getAllByTestId('event-skeleton');
      expect(skeletons.length).toBeGreaterThan(0);

      // Filter buttons are disabled during loading
      const filterButtons = screen.getAllByRole('button', { name: /all|downtime|quality|safety|info/i });
      filterButtons.forEach((btn) => {
        expect(btn).toBeDisabled();
      });

      // Complete fetch
      await act(async () => {
        resolvePromise(mockEvents);
      });

      // Skeleton replaced by table
      expect(screen.queryByTestId('event-list-loading')).not.toBeInTheDocument();
      expect(screen.getByText('Press-01')).toBeInTheDocument();
    });
  });

  describe('Chronological Event Rendering & Details', () => {
    it('renders events in chronological ascending order by createdAt (earliest first)', async () => {
      // Provide events deliberately out of order
      const outOfOrderEvents: EventResponse[] = [
        {
          id: 'ev-late',
          shiftKey: validShiftKey,
          machine: 'Machine-Late',
          category: 'info',
          note: 'Third event',
          createdAt: '2026-11-14T10:00:00Z',
        },
        {
          id: 'ev-early',
          shiftKey: validShiftKey,
          machine: 'Machine-Early',
          category: 'downtime',
          note: 'First event',
          createdAt: '2026-11-14T06:00:00Z',
        },
        {
          id: 'ev-mid',
          shiftKey: validShiftKey,
          machine: 'Machine-Mid',
          category: 'quality',
          note: 'Second event',
          createdAt: '2026-11-14T08:00:00Z',
        },
      ];

      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(outOfOrderEvents);
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Machine-Early');

      const rows = screen.getAllByRole('row').slice(1); // Exclude header row
      expect(rows).toHaveLength(3);

      expect(within(rows[0]).getByText('Machine-Early')).toBeInTheDocument();
      expect(within(rows[1]).getByText('Machine-Mid')).toBeInTheDocument();
      expect(within(rows[2]).getByText('Machine-Late')).toBeInTheDocument();
    });

    it('renders machine, formatted timestamp, category badge, escaped note, and delete button for each event', async () => {
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([mockEvents[0]]);
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Press-01');

      // Machine name
      expect(screen.getByText('Press-01')).toBeInTheDocument();

      // Timestamp
      const formatted = formatEventTimestamp(mockEvents[0].createdAt);
      expect(screen.getByText(formatted)).toBeInTheDocument();

      // Category badge
      const badge = screen.getByText('downtime');
      expect(badge).toBeInTheDocument();
      expect(badge.className).toContain('bg-amber-100');
      expect(badge.className).toContain('text-amber-800');

      // Escaped note
      expect(
        screen.getByText('Hydraulic pressure dropped suddenly, line stopped for 45 minutes.')
      ).toBeInTheDocument();

      // Delete button
      const deleteBtn = screen.getByRole('button', { name: /delete event for press-01/i });
      expect(deleteBtn).toBeInTheDocument();
    });

    it('adheres to design system tokens for all category badges', async () => {
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(mockEvents);
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Press-01');

      const downtimeBadge = screen.getByText('downtime');
      expect(downtimeBadge.className).toContain('bg-amber-100 text-amber-800 border-amber-300');

      const qualityBadge = screen.getByText('quality');
      expect(qualityBadge.className).toContain('bg-purple-100 text-purple-800 border-purple-300');

      const safetyBadge = screen.getByText('safety');
      expect(safetyBadge.className).toContain('bg-red-100 text-red-800 border-red-300 font-semibold');

      const infoBadge = screen.getByText('info');
      expect(infoBadge.className).toContain('bg-slate-100 text-slate-800 border-slate-300');
    });

    it('safely escapes HTML tags in event notes and machine names without executing markup', async () => {
      const xssEvent: EventResponse = {
        id: 'xss-1',
        shiftKey: validShiftKey,
        machine: '<img src=x onerror=alert(1)>',
        category: 'info',
        note: '<script>alert("hacked")</script><b>Bold Note</b>',
        createdAt: '2026-11-14T07:00:00Z',
      };

      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([xssEvent]);
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('<img src=x onerror=alert(1)>');

      // Check text is rendered as pure text
      expect(screen.getByText('<script>alert("hacked")</script><b>Bold Note</b>')).toBeInTheDocument();
      // Ensure no DOM elements were created for script or b
      expect(document.querySelector('script')).toBeNull();
      expect(document.querySelector('b')).toBeNull();
    });

    it('preserves multi-line note breaks with whitespace-pre-wrap', async () => {
      const multilineEvent: EventResponse = {
        id: 'ml-1',
        shiftKey: validShiftKey,
        machine: 'Stamp-01',
        category: 'info',
        note: 'Line 1: Stoppage\nLine 2: Investigation\nLine 3: Cleared',
        createdAt: '2026-11-14T07:00:00Z',
      };

      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([multilineEvent]);
      render(<EventList shiftKey={validShiftKey} />);

      const noteCell = await screen.findByText(/Line 1: Stoppage/i);
      expect(noteCell.className).toContain('whitespace-pre-wrap');
      expect(noteCell.className).toContain('break-words');
    });
  });

  describe('Category Filter Bar & Item Counts', () => {
    it('displays dynamic item counts on all filter buttons', async () => {
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(mockEvents);
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Press-01');

      // 4 total, 1 downtime, 1 quality, 1 safety, 1 info
      expect(screen.getByRole('button', { name: /all \(4\)/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /downtime \(1\)/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /quality \(1\)/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /safety \(1\)/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /info \(1\)/i })).toBeInTheDocument();
    });

    it('filters displayed events by category immediately without triggering network refetch', async () => {
      const listSpy = vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(mockEvents);
      const user = userEvent.setup();
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Press-01');
      expect(listSpy).toHaveBeenCalledTimes(1);

      // Click "Downtime (1)"
      const downtimeFilter = screen.getByRole('button', { name: /downtime \(1\)/i });
      await user.click(downtimeFilter);

      // Downtime button is active
      expect(downtimeFilter).toHaveAttribute('aria-pressed', 'true');
      expect(downtimeFilter.className).toContain('bg-slate-900 text-white');

      // Only Press-01 (downtime) is visible
      expect(screen.getByText('Press-01')).toBeInTheDocument();
      expect(screen.queryByText('Conveyor-B')).not.toBeInTheDocument();
      expect(screen.queryByText('Welder-04')).not.toBeInTheDocument();
      expect(screen.queryByText('Packaging-01')).not.toBeInTheDocument();

      // Ensure no second network call
      expect(listSpy).toHaveBeenCalledTimes(1);

      // Click "Safety (1)"
      const safetyFilter = screen.getByRole('button', { name: /safety \(1\)/i });
      await user.click(safetyFilter);

      expect(safetyFilter).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByText('Welder-04')).toBeInTheDocument();
      expect(screen.queryByText('Press-01')).not.toBeInTheDocument();
      expect(listSpy).toHaveBeenCalledTimes(1);
    });

    it('resets filter to "All" when clicking "All" filter button', async () => {
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(mockEvents);
      const user = userEvent.setup();
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Press-01');

      // Filter by Quality
      await user.click(screen.getByRole('button', { name: /quality \(1\)/i }));
      expect(screen.queryByText('Press-01')).not.toBeInTheDocument();
      expect(screen.getByText('Conveyor-B')).toBeInTheDocument();

      // Reset by clicking All
      await user.click(screen.getByRole('button', { name: /all \(4\)/i }));
      expect(screen.getByText('Press-01')).toBeInTheDocument();
      expect(screen.getByText('Conveyor-B')).toBeInTheDocument();
      expect(screen.getByText('Welder-04')).toBeInTheDocument();
      expect(screen.getByText('Packaging-01')).toBeInTheDocument();
    });
  });

  describe('Empty States', () => {
    it('displays shift empty state when 0 events exist for the shift', async () => {
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([]);
      render(<EventList shiftKey={validShiftKey} />);

      expect(await screen.findByText('No events logged for this shift')).toBeInTheDocument();
      expect(
        screen.getByText(
          'Use the form above to log machine downtime, quality notes, safety incidents, or shift observations.'
        )
      ).toBeInTheDocument();
    });

    it('displays filtered empty state with "Show all events" button when no events match category', async () => {
      // mockEvents has 0 events for a category if we omit it
      const eventsWithoutSafety: EventResponse[] = mockEvents.filter((e) => e.category !== 'safety');
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(eventsWithoutSafety);

      const user = userEvent.setup();
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Press-01');

      // Click "Safety (0)"
      await user.click(screen.getByRole('button', { name: /safety \(0\)/i }));

      // Filtered empty state is shown
      expect(
        screen.getByText('No safety events recorded for this shift.')
      ).toBeInTheDocument();

      const showAllBtn = screen.getByRole('button', { name: /show all events/i });
      expect(showAllBtn).toBeInTheDocument();

      // Clicking "Show all events" resets filter to All
      await user.click(showAllBtn);

      expect(screen.getByText('Press-01')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /all \(3\)/i })).toHaveAttribute('aria-pressed', 'true');
    });
  });

  describe('Cold-Start Alert Behavior', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it('displays persistent cold-start notification after 3 seconds in-flight and clears upon completion', async () => {
      let resolvePromise: (value: EventResponse[]) => void = () => {};
      const pendingPromise = new Promise<EventResponse[]>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(eventsApi, 'listEvents').mockReturnValue(pendingPromise);

      render(<EventList shiftKey={validShiftKey} />);

      // At 2900ms: no cold start banner
      act(() => {
        vi.advanceTimersByTime(2900);
      });
      expect(screen.queryByText(/waking up the database/i)).not.toBeInTheDocument();

      // At 3000ms+: banner appears
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(
        screen.getByText(
          /waking up the database — the first request after an idle period may take up to 20 s\./i
        )
      ).toBeInTheDocument();

      // Resolve request: banner disappears
      await act(async () => {
        resolvePromise(mockEvents);
      });
      expect(screen.queryByText(/waking up the database/i)).not.toBeInTheDocument();
      expect(screen.getByText('Press-01')).toBeInTheDocument();
    });

    it('does not display cold-start banner if request resolves before 3 seconds', async () => {
      let resolvePromise: (value: EventResponse[]) => void = () => {};
      const fastPromise = new Promise<EventResponse[]>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(eventsApi, 'listEvents').mockReturnValue(fastPromise);

      render(<EventList shiftKey={validShiftKey} />);

      act(() => {
        vi.advanceTimersByTime(1000);
      });

      await act(async () => {
        resolvePromise(mockEvents);
      });

      act(() => {
        vi.advanceTimersByTime(2500);
      });

      expect(screen.queryByText(/waking up the database/i)).not.toBeInTheDocument();
    });
  });

  describe('Error State & Retry', () => {
    it('replaces list with error banner displaying RFC 9457 details, trace ID, and invokes onError callback', async () => {
      const onErrorMock = vi.fn();
      const apiError = new ApiError(500, 'Internal Server Error', {
        type: 'https://api.shift-copilot.example.com/errors/internal',
        title: 'Internal Server Error',
        status: 500,
        detail: 'Database pool connection timed out.',
        traceId: 'tr-fetch-fail-1234',
      });

      vi.spyOn(eventsApi, 'listEvents').mockRejectedValue(apiError);
      render(<EventList shiftKey={validShiftKey} onError={onErrorMock} />);

      expect(await screen.findByText('Failed to load shift events')).toBeInTheDocument();
      expect(screen.getByText('Database pool connection timed out.')).toBeInTheDocument();
      expect(screen.getByText('Trace ID: tr-fetch-fail-1234')).toBeInTheDocument();

      expect(onErrorMock).toHaveBeenCalledTimes(1);
      expect(onErrorMock).toHaveBeenCalledWith(apiError);
    });

    it('retries fetching events when clicking "Retry" button', async () => {
      const listSpy = vi
        .spyOn(eventsApi, 'listEvents')
        .mockRejectedValueOnce(new Error('Network disconnected'))
        .mockResolvedValueOnce(mockEvents);

      const user = userEvent.setup();
      render(<EventList shiftKey={validShiftKey} />);

      expect(await screen.findByText('Failed to load shift events')).toBeInTheDocument();
      expect(screen.getByText('Network disconnected')).toBeInTheDocument();

      const retryBtn = screen.getByRole('button', { name: /retry/i });
      await user.click(retryBtn);

      expect(listSpy).toHaveBeenCalledTimes(2);
      expect(await screen.findByText('Press-01')).toBeInTheDocument();
      expect(screen.queryByText('Failed to load shift events')).not.toBeInTheDocument();
    });
  });

  describe('Event Deletion Flow', () => {
    it('prompts user confirmation, calls eventsApi.deleteEvent, updates counts, and fires onEventDeleted', async () => {
      const deleteSpy = vi.spyOn(eventsApi, 'deleteEvent').mockResolvedValue(undefined);
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([...mockEvents]);
      const onEventDeletedMock = vi.fn();

      const user = userEvent.setup();
      render(
        <EventList shiftKey={validShiftKey} onEventDeleted={onEventDeletedMock} />
      );

      await screen.findByText('Press-01');

      // Click delete button for Press-01
      const deleteBtn = screen.getByRole('button', { name: /delete event for press-01/i });
      await user.click(deleteBtn);

      // Inline confirmation buttons appear
      const confirmBtn = screen.getByRole('button', { name: /confirm delete for press-01/i });
      const cancelBtn = screen.getByRole('button', { name: /cancel delete for press-01/i });
      expect(confirmBtn).toBeInTheDocument();
      expect(cancelBtn).toBeInTheDocument();

      // Click confirm
      await user.click(confirmBtn);

      expect(deleteSpy).toHaveBeenCalledTimes(1);
      expect(deleteSpy).toHaveBeenCalledWith('11111111-1111-1111-1111-111111111111');

      // Event is removed from DOM
      expect(screen.queryByText('Press-01')).not.toBeInTheDocument();

      // Callback invoked
      expect(onEventDeletedMock).toHaveBeenCalledWith('11111111-1111-1111-1111-111111111111');

      // Total count decremented from 4 to 3, Downtime count from 1 to 0
      expect(screen.getByRole('button', { name: /all \(3\)/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /downtime \(0\)/i })).toBeInTheDocument();
    });

    it('cancels deletion when clicking "Cancel"', async () => {
      const deleteSpy = vi.spyOn(eventsApi, 'deleteEvent');
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([...mockEvents]);

      const user = userEvent.setup();
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Press-01');

      const deleteBtn = screen.getByRole('button', { name: /delete event for press-01/i });
      await user.click(deleteBtn);

      const cancelBtn = screen.getByRole('button', { name: /cancel delete for press-01/i });
      await user.click(cancelBtn);

      expect(deleteSpy).not.toHaveBeenCalled();
      expect(screen.getByRole('button', { name: /delete event for press-01/i })).toBeInTheDocument();
      expect(screen.getByText('Press-01')).toBeInTheDocument();
    });

    it('shows loading state on delete button while deletion is in flight', async () => {
      let resolveDelete: () => void = () => {};
      const pendingDeletePromise = new Promise<void>((res) => {
        resolveDelete = res;
      });
      vi.spyOn(eventsApi, 'deleteEvent').mockReturnValue(pendingDeletePromise);
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([...mockEvents]);

      const user = userEvent.setup();
      render(<EventList shiftKey={validShiftKey} />);

      await screen.findByText('Press-01');

      const deleteBtn = screen.getByRole('button', { name: /delete event for press-01/i });
      await user.click(deleteBtn);

      const confirmBtn = screen.getByRole('button', { name: /confirm delete for press-01/i });
      await user.click(confirmBtn);

      // Button is in loading state and disabled
      expect(screen.getByText(/deleting\.\.\./i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /confirm delete for press-01/i })).toBeDisabled();

      // Resolve deletion
      await act(async () => {
        resolveDelete();
      });

      expect(screen.queryByText('Press-01')).not.toBeInTheDocument();
    });

    it('displays error banner with trace ID when deletion fails and retains the event', async () => {
      const onErrorMock = vi.fn();
      const deleteError = new ApiError(409, 'Conflict', {
        type: 'https://api.shift-copilot.example.com/errors/conflict',
        title: 'Conflict',
        status: 409,
        detail: 'Cannot delete event locked in generated report.',
        traceId: 'tr-delete-fail-999',
      });
      vi.spyOn(eventsApi, 'deleteEvent').mockRejectedValue(deleteError);
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([...mockEvents]);

      const user = userEvent.setup();
      render(<EventList shiftKey={validShiftKey} onError={onErrorMock} />);

      await screen.findByText('Press-01');

      const deleteBtn = screen.getByRole('button', { name: /delete event for press-01/i });
      await user.click(deleteBtn);

      const confirmBtn = screen.getByRole('button', { name: /confirm delete for press-01/i });
      await user.click(confirmBtn);

      // Error banner is rendered with detail and traceId
      expect(
        await screen.findByText('Cannot delete event locked in generated report.')
      ).toBeInTheDocument();
      expect(screen.getByText('Trace ID: tr-delete-fail-999')).toBeInTheDocument();

      // Event is retained in the list
      expect(screen.getByText('Press-01')).toBeInTheDocument();

      // onError is invoked
      expect(onErrorMock).toHaveBeenCalledWith(deleteError);

      // Error banner can be dismissed
      const dismissBtn = screen.getByRole('button', { name: /dismiss error/i });
      await user.click(dismissBtn);
      expect(
        screen.queryByText('Cannot delete event locked in generated report.')
      ).not.toBeInTheDocument();
    });
  });

  describe('Race Condition Prevention', () => {
    it('cancels/ignores stale response when shiftKey rapidly changes', async () => {
      let resolveFirst: (v: EventResponse[]) => void = () => {};
      let resolveSecond: (v: EventResponse[]) => void = () => {};

      const firstPromise = new Promise<EventResponse[]>((res) => {
        resolveFirst = res;
      });
      const secondPromise = new Promise<EventResponse[]>((res) => {
        resolveSecond = res;
      });

      const listSpy = vi.spyOn(eventsApi, 'listEvents');
      listSpy.mockReturnValueOnce(firstPromise);
      listSpy.mockReturnValueOnce(secondPromise);

      const { rerender } = render(<EventList shiftKey="2026-11-14-early" />);

      // Rapidly switch shiftKey to late
      rerender(<EventList shiftKey="2026-11-14-late" />);

      // Second response resolves first
      const lateEvents: EventResponse[] = [
        {
          id: 'late-1',
          shiftKey: '2026-11-14-late',
          machine: 'Machine-Late-Shift',
          category: 'info',
          note: 'Late shift observation',
          createdAt: '2026-11-14T14:30:00Z',
        },
      ];

      await act(async () => {
        resolveSecond(lateEvents);
      });

      expect(screen.getByText('Machine-Late-Shift')).toBeInTheDocument();

      // Later, first (stale) response resolves
      await act(async () => {
        resolveFirst(mockEvents);
      });

      // Stale events must NOT overwrite current shift
      expect(screen.queryByText('Press-01')).not.toBeInTheDocument();
      expect(screen.getByText('Machine-Late-Shift')).toBeInTheDocument();
    });
  });

  describe('Disabled State & RefreshKey', () => {
    it('disables all interactive controls when disabled={true}', async () => {
      vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(mockEvents);
      render(<EventList shiftKey={validShiftKey} disabled={true} />);

      await screen.findByText('Press-01');

      // Filter buttons disabled
      const filterButtons = screen.getAllByRole('button', { name: /all|downtime|quality|safety|info/i });
      filterButtons.forEach((btn) => {
        expect(btn).toBeDisabled();
      });

      // Delete buttons disabled
      const deleteButtons = screen.getAllByRole('button', { name: /delete event for/i });
      deleteButtons.forEach((btn) => {
        expect(btn).toBeDisabled();
      });
    });

    it('refetches events when refreshKey changes', async () => {
      const listSpy = vi.spyOn(eventsApi, 'listEvents').mockResolvedValue(mockEvents);

      const { rerender } = render(<EventList shiftKey={validShiftKey} refreshKey={1} />);

      await screen.findByText('Press-01');
      expect(listSpy).toHaveBeenCalledTimes(1);

      // Change refreshKey
      await act(async () => {
        rerender(<EventList shiftKey={validShiftKey} refreshKey={2} />);
      });

      expect(listSpy).toHaveBeenCalledTimes(2);
      expect(await screen.findByText('Press-01')).toBeInTheDocument();
    });
  });
});
