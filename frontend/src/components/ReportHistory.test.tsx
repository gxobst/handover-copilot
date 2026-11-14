import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import { ReportHistory } from './ReportHistory';
import { reportsApi } from '../services';
import { ApiError } from '../services/errors';
import type { ReportResponse, ReportSummary } from '../types/api';

describe('ReportHistory Component', () => {
  const shiftKey = '2026-11-14-early';

  const mockSummaries: ReportSummary[] = [
    {
      id: 'report-v3-id',
      shiftKey,
      version: 3,
      modelUsed: 'google/gemini-3.5-flash-lite',
      eventCount: 6,
      createdAt: '2026-11-14T16:00:00Z',
    },
    {
      id: 'report-v2-id',
      shiftKey,
      version: 2,
      modelUsed: 'google/gemini-3.5-flash-lite',
      eventCount: 4,
      createdAt: '2026-11-14T15:00:00Z',
    },
    {
      id: 'report-v1-id',
      shiftKey,
      version: 1,
      modelUsed: 'google/gemini-3.5-flash-lite',
      eventCount: 2,
      createdAt: '2026-11-14T14:00:00Z',
    },
  ];

  const mockV3Detail: ReportResponse = {
    id: 'report-v3-id',
    shiftKey,
    version: 3,
    summary: 'Version 3 Summary: Final synthesized shift report with 6 events.',
    openActions: [
      {
        action: 'Handover tools to late shift',
        priority: 'medium',
        owner: 'Lead Operator',
      },
    ],
    safetyNotes: ['All safety guards inspected and secured.'],
    modelUsed: 'google/gemini-3.5-flash-lite',
    eventCount: 6,
    createdAt: '2026-11-14T16:00:00Z',
  };

  const mockV2Detail: ReportResponse = {
    id: 'report-v2-id',
    shiftKey,
    version: 2,
    summary: 'Version 2 Summary: Mid-shift update after tooling calibration.',
    openActions: [
      {
        action: 'Monitor Press-01 pressure gauge',
        priority: 'high',
        owner: 'Mechanical Team',
      },
    ],
    safetyNotes: ['Caution: Hydraulic line temperature elevated.'],
    modelUsed: 'google/gemini-3.5-flash-lite',
    eventCount: 4,
    createdAt: '2026-11-14T15:00:00Z',
  };

  const mockV1Detail: ReportResponse = {
    id: 'report-v1-id',
    shiftKey,
    version: 1,
    summary: 'Version 1 Summary: Initial report generation at mid-shift.',
    openActions: [
      {
        action: 'Clean line 2 scrap bin',
        priority: 'low',
        owner: 'Line Operator',
      },
    ],
    safetyNotes: [],
    modelUsed: 'google/gemini-3.5-flash-lite',
    eventCount: 2,
    createdAt: '2026-11-14T14:00:00Z',
  };

  const mockDetailMap: Record<string, ReportResponse> = {
    'report-v3-id': mockV3Detail,
    'report-v2-id': mockV2Detail,
    'report-v1-id': mockV1Detail,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(reportsApi, 'listReports').mockResolvedValue([...mockSummaries]);
    vi.spyOn(reportsApi, 'getReport').mockImplementation((id: string) => {
      if (mockDetailMap[id]) {
        return Promise.resolve(mockDetailMap[id]);
      }
      return Promise.reject(
        new ApiError(404, 'Not Found', {
          type: 'about:blank',
          title: 'Not Found',
          status: 404,
          detail: 'Report not found',
          traceId: 'trace-404',
        })
      );
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  describe('List Rendering & Presentation', () => {
    it('fetches and renders report version summaries in descending version order', async () => {
      // Intentionally provide unordered array to test sorting
      vi.spyOn(reportsApi, 'listReports').mockResolvedValue([
        mockSummaries[2],
        mockSummaries[0],
        mockSummaries[1],
      ]);

      render(<ReportHistory shiftKey={shiftKey} />);

      // Await report list and detail
      await screen.findByText('Version 3 Summary: Final synthesized shift report with 6 events.');

      // Check header
      expect(screen.getByText('Report History')).toBeInTheDocument();
      expect(screen.getByText('Generated Versions (3)')).toBeInTheDocument();

      // Check version list items order scoped to history list
      const versionList = screen.getByRole('list', { name: /report version history/i });
      const versionItems = within(versionList).getAllByRole('listitem');
      expect(versionItems.length).toBe(3);

      expect(versionItems[0]).toHaveTextContent('v3(Latest)');
      expect(versionItems[0]).toHaveTextContent('6 events');
      expect(versionItems[0]).toHaveTextContent('google/gemini-3.5-flash-lite');

      expect(versionItems[1]).toHaveTextContent('v2');
      expect(versionItems[1]).toHaveTextContent('4 events');

      expect(versionItems[2]).toHaveTextContent('v1');
      expect(versionItems[2]).toHaveTextContent('2 events');
    });

    it('styles the latest version badge distinctly from past versions', async () => {
      render(<ReportHistory shiftKey={shiftKey} />);

      await screen.findByText('Version 3 Summary: Final synthesized shift report with 6 events.');

      const versionList = screen.getByRole('list', { name: /report version history/i });
      const latestBadge = within(versionList).getByText(/v3/);
      expect(latestBadge.className).toContain('bg-emerald-100');
      expect(latestBadge.className).toContain('text-emerald-800');
      expect(latestBadge.className).toContain('border-emerald-300');

      const pastBadge = within(versionList).getByText('v2');
      expect(pastBadge.className).toContain('bg-slate-100');
      expect(pastBadge.className).toContain('text-slate-700');
    });

    it('indicates current selection with aria-selected="true" and visual highlight', async () => {
      render(<ReportHistory shiftKey={shiftKey} />);

      await screen.findByText('Version 3 Summary: Final synthesized shift report with 6 events.');

      const buttons = screen.getAllByRole('button', { name: /version \d for shift/i });
      expect(buttons[0]).toHaveAttribute('aria-selected', 'true');
      expect(buttons[0].className).toContain('ring-2 ring-slate-900');
      expect(buttons[1]).toHaveAttribute('aria-selected', 'false');
    });
  });

  describe('Default Selection & Detail Snapshot Inspection', () => {
    it('automatically selects latest version by default and fetches full snapshot', async () => {
      const onSelectReport = vi.fn();
      render(<ReportHistory shiftKey={shiftKey} onSelectReport={onSelectReport} />);

      await screen.findByText('Version 3 Summary: Final synthesized shift report with 6 events.');

      expect(reportsApi.getReport).toHaveBeenCalledWith('report-v3-id', undefined);
      expect(screen.getByText('Executive Summary')).toBeInTheDocument();
      expect(screen.getByText('All safety guards inspected and secured.')).toBeInTheDocument();
      expect(screen.getByText('Handover tools to late shift')).toBeInTheDocument();

      // Latest version should NOT display the historical banner
      expect(screen.queryByTestId('historical-version-banner')).not.toBeInTheDocument();
    });

    it('respects initialSelectedId when provided and displays that snapshot', async () => {
      render(<ReportHistory shiftKey={shiftKey} initialSelectedId="report-v2-id" />);

      await screen.findByText('Version 2 Summary: Mid-shift update after tooling calibration.');

      expect(reportsApi.getReport).toHaveBeenCalledWith('report-v2-id', undefined);
      expect(screen.getByText('Caution: Hydraulic line temperature elevated.')).toBeInTheDocument();
      expect(screen.getByText('Monitor Press-01 pressure gauge')).toBeInTheDocument();

      // Historical version banner should be visible for v2
      const banner = screen.getByTestId('historical-version-banner');
      expect(banner).toBeInTheDocument();
      expect(screen.getByText('Historical Version 2 Snapshot (Read-Only / Immutable)')).toBeInTheDocument();
    });

    it('switches snapshot and displays historical banner when an older version is clicked', async () => {
      render(<ReportHistory shiftKey={shiftKey} />);

      await screen.findByText('Version 3 Summary: Final synthesized shift report with 6 events.');
      expect(screen.queryByTestId('historical-version-banner')).not.toBeInTheDocument();

      // Click version 1
      const v1Button = screen.getByRole('button', { name: /version 1 for shift/i });
      fireEvent.click(v1Button);

      await screen.findByText('Version 1 Summary: Initial report generation at mid-shift.');
      expect(reportsApi.getReport).toHaveBeenCalledWith('report-v1-id', undefined);

      // Verify historical banner appeared
      const banner = screen.getByTestId('historical-version-banner');
      expect(banner).toBeInTheDocument();
      expect(screen.getByText('Historical Version 1 Snapshot (Read-Only / Immutable)')).toBeInTheDocument();
      expect(v1Button).toHaveAttribute('aria-selected', 'true');
    });
  });

  describe('Side-by-Side Comparison Mode', () => {
    it('shows comparison toggle when historical version is selected and multiple versions exist', async () => {
      render(<ReportHistory shiftKey={shiftKey} />);

      await screen.findByText('Version 3 Summary: Final synthesized shift report with 6 events.');

      // Toggle is not shown when latest is selected
      expect(screen.queryByRole('button', { name: /side-by-side comparison/i })).not.toBeInTheDocument();

      // Click version 2
      const v2Button = screen.getByRole('button', { name: /version 2 for shift/i });
      fireEvent.click(v2Button);

      await screen.findByText('Version 2 Summary: Mid-shift update after tooling calibration.');

      // Comparison toggle button should now be visible
      const toggleButton = screen.getByRole('button', { name: /switch to side-by-side comparison/i });
      expect(toggleButton).toBeInTheDocument();
      expect(toggleButton).toHaveTextContent('Side-by-side comparison');

      // Click comparison toggle to activate side-by-side mode
      fireEvent.click(toggleButton);

      // Verify side-by-side container and columns
      const comparisonContainer = screen.getByTestId('side-by-side-comparison');
      expect(comparisonContainer).toBeInTheDocument();
      expect(comparisonContainer.className).toContain('grid grid-cols-1 lg:grid-cols-2 gap-4');

      // Left column: Historical
      expect(screen.getByText('Selected Historical Snapshot (v2)')).toBeInTheDocument();
      expect(screen.getByText('Caution: Hydraulic line temperature elevated.')).toBeInTheDocument();

      // Right column: Latest
      expect(screen.getByText('Current Latest Report (v3)')).toBeInTheDocument();
      expect(screen.getByText('All safety guards inspected and secured.')).toBeInTheDocument();

      // Toggle back to single view
      const singleViewButton = screen.getByRole('button', { name: /switch to single snapshot view/i });
      expect(singleViewButton).toHaveTextContent('Single snapshot view');
      fireEvent.click(singleViewButton);

      expect(screen.queryByTestId('side-by-side-comparison')).not.toBeInTheDocument();
    });

    it('hides side-by-side toggle and shows guard note when only 1 version exists', async () => {
      vi.spyOn(reportsApi, 'listReports').mockResolvedValue([mockSummaries[2]]); // only v1
      vi.spyOn(reportsApi, 'getReport').mockResolvedValue(mockV1Detail);

      render(<ReportHistory shiftKey={shiftKey} />);

      await screen.findByText('Version 1 Summary: Initial report generation at mid-shift.');

      expect(screen.queryByRole('button', { name: /side-by-side comparison/i })).not.toBeInTheDocument();
      const guardNote = screen.getByTestId('single-version-guard');
      expect(guardNote).toBeInTheDocument();
      expect(
        screen.getByText('Only one version exists for this shift. Regenerate to create version 2.')
      ).toBeInTheDocument();
    });
  });

  describe('Empty & Edge Cases', () => {
    it('displays high-contrast empty state container when report list is empty', async () => {
      vi.spyOn(reportsApi, 'listReports').mockResolvedValue([]);

      render(<ReportHistory shiftKey={shiftKey} />);

      await screen.findByTestId('empty-history-state');

      expect(screen.getByText('No report history available')).toBeInTheDocument();
      expect(
        screen.getByText(`No handover reports have been generated yet for shift ${shiftKey}.`)
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Log shift events on the Shift Board and generate a handover report/i)
      ).toBeInTheDocument();
    });

    it('displays generic empty message when shiftKey is not provided', async () => {
      vi.spyOn(reportsApi, 'listReports').mockResolvedValue([]);

      render(<ReportHistory />);

      await screen.findByTestId('empty-history-state');

      expect(screen.getByText('No report history available')).toBeInTheDocument();
      expect(screen.getByText('No handover reports have been generated yet.')).toBeInTheDocument();
    });

    it('refetches and updates selection when shiftKey prop changes', async () => {
      const { rerender } = render(<ReportHistory shiftKey="2026-11-14-early" />);

      await screen.findByText('Version 3 Summary: Final synthesized shift report with 6 events.');
      expect(reportsApi.listReports).toHaveBeenCalledWith('2026-11-14-early', 20);

      const lateReport: ReportResponse = {
        id: 'report-late-v1',
        shiftKey: '2026-11-14-late',
        version: 1,
        summary: 'Late Shift Handover Version 1.',
        openActions: [],
        safetyNotes: [],
        modelUsed: 'google/gemini-3.5-flash-lite',
        eventCount: 1,
        createdAt: '2026-11-14T22:00:00Z',
      };

      vi.spyOn(reportsApi, 'listReports').mockResolvedValue([
        {
          id: 'report-late-v1',
          shiftKey: '2026-11-14-late',
          version: 1,
          modelUsed: 'google/gemini-3.5-flash-lite',
          eventCount: 1,
          createdAt: '2026-11-14T22:00:00Z',
        },
      ]);
      vi.spyOn(reportsApi, 'getReport').mockResolvedValue(lateReport);

      rerender(<ReportHistory shiftKey="2026-11-14-late" />);

      await screen.findByText('Late Shift Handover Version 1.');
      expect(reportsApi.listReports).toHaveBeenCalledWith('2026-11-14-late', 20);
    });
  });

  describe('Asynchronous, Cold-Start & Race Conditions', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it('displays cold-start notification banner when listReports exceeds 3000ms', async () => {
      let resolveList: (v: ReportSummary[]) => void = () => {};
      const delayedPromise = new Promise<ReportSummary[]>((res) => {
        resolveList = res;
      });
      vi.spyOn(reportsApi, 'listReports').mockReturnValue(delayedPromise);

      render(<ReportHistory shiftKey={shiftKey} />);

      // At 2900ms: banner not visible yet
      act(() => {
        vi.advanceTimersByTime(2900);
      });
      expect(screen.queryByTestId('cold-start-banner')).not.toBeInTheDocument();

      // At 3100ms: banner appears with exact text
      act(() => {
        vi.advanceTimersByTime(200);
      });

      const coldStartBanner = screen.getByTestId('cold-start-banner');
      expect(coldStartBanner).toBeInTheDocument();
      expect(
        screen.getByText(
          'Waking up the database — the first request after an idle period may take up to 20 s.'
        )
      ).toBeInTheDocument();

      // Resolve list promise
      await act(async () => {
        resolveList([...mockSummaries]);
      });

      expect(screen.queryByTestId('cold-start-banner')).not.toBeInTheDocument();
    });

    it('does not display cold-start banner when list request completes under 3000ms', async () => {
      render(<ReportHistory shiftKey={shiftKey} />);

      await act(async () => {
        vi.advanceTimersByTime(1500);
      });

      expect(screen.queryByTestId('cold-start-banner')).not.toBeInTheDocument();
    });

    it('protects against fast version-switching race conditions', async () => {
      let resolveV1: (v: ReportResponse) => void = () => {};
      let resolveV2: (v: ReportResponse) => void = () => {};

      const v1Promise = new Promise<ReportResponse>((res) => {
        resolveV1 = res;
      });
      const v2Promise = new Promise<ReportResponse>((res) => {
        resolveV2 = res;
      });

      // Initial render resolves v3 immediately
      vi.spyOn(reportsApi, 'getReport').mockImplementation((id: string) => {
        if (id === 'report-v3-id') return Promise.resolve(mockV3Detail);
        if (id === 'report-v1-id') return v1Promise;
        if (id === 'report-v2-id') return v2Promise;
        return Promise.reject(new Error('Unknown ID'));
      });

      render(<ReportHistory shiftKey={shiftKey} />);

      await act(async () => {
        // flush initial mount
      });
      expect(screen.getByText('Version 3 Summary: Final synthesized shift report with 6 events.')).toBeInTheDocument();

      // Click v1 first
      const v1Button = screen.getByRole('button', { name: /version 1 for shift/i });
      fireEvent.click(v1Button);

      // Rapidly click v2 second
      const v2Button = screen.getByRole('button', { name: /version 2 for shift/i });
      fireEvent.click(v2Button);

      // Now resolve v2 LATER than click
      await act(async () => {
        resolveV2(mockV2Detail);
      });

      expect(screen.getByText('Version 2 Summary: Mid-shift update after tooling calibration.')).toBeInTheDocument();

      // Now resolve v1 (stale response)
      await act(async () => {
        resolveV1(mockV1Detail);
      });

      // Crucial assertion: v1 should have been discarded; v2 remains visible
      expect(screen.getByText('Version 2 Summary: Mid-shift update after tooling calibration.')).toBeInTheDocument();
      expect(
        screen.queryByText('Version 1 Summary: Initial report generation at mid-shift.')
      ).not.toBeInTheDocument();
    });
  });

  describe('Error Handling & RFC 9457 Problem Details', () => {
    it('renders RFC 9457 error card and retries when listReports fails', async () => {
      const error = new ApiError(500, 'Internal Server Error', {
        type: 'about:blank',
        title: 'Internal Server Error',
        status: 500,
        detail: 'Database connection lost',
        traceId: 'trace-list-500',
      });
      vi.spyOn(reportsApi, 'listReports')
        .mockRejectedValueOnce(error)
        .mockResolvedValueOnce([...mockSummaries]);

      render(<ReportHistory shiftKey={shiftKey} />);

      const errorAlert = await screen.findByTestId('history-list-error');
      expect(errorAlert).toBeInTheDocument();
      expect(screen.getByText('Internal Server Error')).toBeInTheDocument();
      expect(screen.getByText('Database connection lost')).toBeInTheDocument();
      expect(screen.getByText('Trace ID: trace-list-500')).toBeInTheDocument();

      // Click Try Again
      const retryBtn = screen.getByRole('button', { name: /try again/i });
      fireEvent.click(retryBtn);

      // After retry, list and detail load successfully
      await screen.findByText('Version 3 Summary: Final synthesized shift report with 6 events.');
      expect(screen.queryByTestId('history-list-error')).not.toBeInTheDocument();
    });

    it('renders inline error card when getReport returns HTTP 404', async () => {
      vi.spyOn(reportsApi, 'getReport').mockRejectedValue(
        new ApiError(404, 'Not Found', {
          type: 'about:blank',
          title: 'Not Found',
          status: 404,
          detail: 'Report snapshot was deleted',
          traceId: 'trace-detail-404',
        })
      );

      render(<ReportHistory shiftKey={shiftKey} />);

      await screen.findByTestId('report-detail-error');

      expect(screen.getByText('Report snapshot not found')).toBeInTheDocument();
      expect(screen.getByText('Report snapshot was deleted')).toBeInTheDocument();
      expect(screen.getByText('Trace ID: trace-detail-404')).toBeInTheDocument();
    });
  });

  describe('Security & XSS Prevention', () => {
    it('safely renders untrusted HTML/scripts as literal text without executing', async () => {
      const xssSummary: ReportSummary = {
        id: 'report-xss-id',
        shiftKey,
        version: 1,
        modelUsed: '<b onfocus=alert(1)>google/model</b>',
        eventCount: 1,
        createdAt: '2026-11-14T14:00:00Z',
      };

      const xssDetail: ReportResponse = {
        id: 'report-xss-id',
        shiftKey,
        version: 1,
        summary: '<script>window.pwned=true</script><img src="x" onerror="alert(1)">',
        openActions: [
          {
            action: '<iframe src="malicious.html"></iframe>',
            priority: 'high',
            owner: '<svg onload="alert(1)"></svg>',
          },
        ],
        safetyNotes: ['<script>evil()</script>'],
        modelUsed: '<b onfocus=alert(1)>google/model</b>',
        eventCount: 1,
        createdAt: '2026-11-14T14:00:00Z',
      };

      vi.spyOn(reportsApi, 'listReports').mockResolvedValue([xssSummary]);
      vi.spyOn(reportsApi, 'getReport').mockResolvedValue(xssDetail);

      const { container } = render(<ReportHistory shiftKey={shiftKey} />);

      await screen.findByText('<script>window.pwned=true</script><img src="x" onerror="alert(1)">');

      expect(screen.getByText('<iframe src="malicious.html"></iframe>')).toBeInTheDocument();
      expect(screen.getByText('<svg onload="alert(1)"></svg>')).toBeInTheDocument();
      expect(screen.getByText('<script>evil()</script>')).toBeInTheDocument();

      // Ensure no raw script/iframe tags were created
      expect(container.querySelectorAll('script').length).toBe(0);
      expect(container.querySelectorAll('iframe').length).toBe(0);
    });
  });
});
