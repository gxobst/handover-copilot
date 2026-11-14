import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReportView } from './ReportView';
import { ApiError } from '../services/errors';
import type { ReportResponse, OpenAction } from '../types/api';

describe('ReportView Component', () => {
  const mockReport: ReportResponse = {
    id: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    shiftKey: '2026-11-14-early',
    version: 2,
    summary: 'Shift operated at 92% efficiency.\nLine 2 experienced a 20-minute hydraulic pressure anomaly.',
    safetyNotes: [
      'Line 2 hydraulic oil drip cleaned and absorbent pads placed.',
      'Forklift traffic heavy near Loading Bay 3 during material restock.',
    ],
    openActions: [
      {
        priority: 'high',
        action: 'Replace worn hydraulic seal on Line 2 secondary valve.',
        owner: 'Alex Chen (Maintenance)',
      },
      {
        priority: 'medium',
        action: 'Inspect sheet calibration tolerances on Station B.',
        owner: 'Maria Gomez (Quality)',
      },
      {
        priority: 'low',
        action: 'Restock absorbent pads at Bay 3 safety locker.',
        owner: 'Jordan Lee (Safety)',
      },
    ],
    modelUsed: 'google/gemini-3.5-flash-lite',
    eventCount: 14,
    createdAt: '2026-11-14T14:30:00Z',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('Full Report Rendering', () => {
    it('renders metadata bar with version, shiftKey, modelUsed, formatted timestamp, event count, and report ID', () => {
      render(<ReportView report={mockReport} />);

      // Metadata Bar
      const metaBar = screen.getByTestId('report-metadata-bar');
      expect(metaBar).toBeInTheDocument();

      expect(within(metaBar).getByText('Version 2')).toBeInTheDocument();
      expect(within(metaBar).getByText('2026-11-14-early')).toBeInTheDocument();
      expect(within(metaBar).getByText('google/gemini-3.5-flash-lite')).toBeInTheDocument();
      expect(within(metaBar).getByText('14 events synthesized')).toBeInTheDocument();
      expect(within(metaBar).getByText(/ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890/)).toBeInTheDocument();

      // Timestamp check (local time format YYYY-MM-DD HH:mm)
      const expectedDateRegex = /\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}/;
      expect(within(metaBar).getByText(expectedDateRegex)).toBeInTheDocument();
    });

    it('renders executive summary section with title and multiline summary text', () => {
      render(<ReportView report={mockReport} />);

      const summaryHeading = screen.getByRole('heading', { name: /Executive Summary/i });
      expect(summaryHeading).toBeInTheDocument();

      expect(
        screen.getByText((content) =>
          content.includes('Shift operated at 92% efficiency.') &&
          content.includes('Line 2 experienced a 20-minute hydraulic pressure anomaly.')
        )
      ).toBeInTheDocument();
    });

    it('renders safety notes section with warning container and list items', () => {
      render(<ReportView report={mockReport} />);

      const safetyHeading = screen.getByRole('heading', { name: /Safety Notes/i });
      expect(safetyHeading).toBeInTheDocument();

      const note1 = screen.getByText('Line 2 hydraulic oil drip cleaned and absorbent pads placed.');
      const note2 = screen.getByText('Forklift traffic heavy near Loading Bay 3 during material restock.');
      expect(note1).toBeInTheDocument();
      expect(note2).toBeInTheDocument();

      // Warning container styling (red)
      const safetySection = safetyHeading.closest('section');
      expect(safetySection).toHaveClass('bg-red-50', 'border-red-300', 'text-red-900');
    });

    it('renders open actions table with correct semantic columns, descriptions, and owners', () => {
      render(<ReportView report={mockReport} />);

      const actionsHeading = screen.getByRole('heading', { name: /Open Actions/i });
      expect(actionsHeading).toBeInTheDocument();

      // Table column headers
      expect(screen.getByRole('columnheader', { name: /Priority/i })).toBeInTheDocument();
      expect(screen.getByRole('columnheader', { name: /Action Item/i })).toBeInTheDocument();
      expect(screen.getByRole('columnheader', { name: /Owner/i })).toBeInTheDocument();

      // Action items
      expect(screen.getByText('Replace worn hydraulic seal on Line 2 secondary valve.')).toBeInTheDocument();
      expect(screen.getByText('Alex Chen (Maintenance)')).toBeInTheDocument();

      expect(screen.getByText('Inspect sheet calibration tolerances on Station B.')).toBeInTheDocument();
      expect(screen.getByText('Maria Gomez (Quality)')).toBeInTheDocument();

      expect(screen.getByText('Restock absorbent pads at Bay 3 safety locker.')).toBeInTheDocument();
      expect(screen.getByText('Jordan Lee (Safety)')).toBeInTheDocument();
    });
  });

  describe('Action Priority Badges', () => {
    it('applies red bold styling for high priority action tags', () => {
      render(<ReportView report={mockReport} />);
      const highBadge = screen.getByText('high');
      expect(highBadge).toHaveClass('text-red-700', 'bg-red-50', 'border-red-200', 'font-bold');
    });

    it('applies amber styling for medium priority action tags', () => {
      render(<ReportView report={mockReport} />);
      const mediumBadge = screen.getByText('medium');
      expect(mediumBadge).toHaveClass('text-amber-700', 'bg-amber-50', 'border-amber-200', 'font-medium');
    });

    it('applies slate neutral styling for low priority action tags', () => {
      render(<ReportView report={mockReport} />);
      const lowBadge = screen.getByText('low');
      expect(lowBadge).toHaveClass('text-slate-600', 'bg-slate-50', 'border-slate-200');
    });

    it('safely falls back to slate neutral styling for unrecognized priority values without crashing', () => {
      const reportWithUnknownPriority: ReportResponse = {
        ...mockReport,
        openActions: [
          {
            priority: 'urgent' as unknown as OpenAction['priority'],
            action: 'Emergency shutdown drill review.',
            owner: 'Ops Lead',
          },
        ],
      };

      render(<ReportView report={reportWithUnknownPriority} />);
      const fallbackBadge = screen.getByText('urgent');
      expect(fallbackBadge).toBeInTheDocument();
      expect(fallbackBadge).toHaveClass('text-slate-600', 'bg-slate-50', 'border-slate-200');
    });
  });

  describe('Safety Notes Empty & Present States', () => {
    it('renders reassuring calm empty state with emerald styling when safetyNotes is empty', () => {
      const reportWithNoSafety: ReportResponse = {
        ...mockReport,
        safetyNotes: [],
      };

      render(<ReportView report={reportWithNoSafety} />);

      const emptyMessage = screen.getByText('No safety incidents or hazards flagged for this shift.');
      expect(emptyMessage).toBeInTheDocument();

      const safetySection = screen.getByRole('heading', { name: /Safety Notes/i }).closest('section');
      expect(safetySection).toHaveClass('bg-emerald-50', 'border-emerald-200', 'text-emerald-800');
    });
  });

  describe('Open Actions Empty State', () => {
    it('renders empty prompt when openActions array is empty', () => {
      const reportWithNoActions: ReportResponse = {
        ...mockReport,
        openActions: [],
      };

      render(<ReportView report={reportWithNoActions} />);

      expect(screen.getByText('No open action items pending for oncoming shift.')).toBeInTheDocument();
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });
  });

  describe('Executive Summary Empty Fallback', () => {
    it('renders fallback prompt when summary is an empty string', () => {
      const reportWithEmptySummary: ReportResponse = {
        ...mockReport,
        summary: '',
      };

      render(<ReportView report={reportWithEmptySummary} />);
      expect(screen.getByText('No executive summary provided.')).toBeInTheDocument();
    });

    it('renders fallback prompt when summary is whitespace-only', () => {
      const reportWithWhitespaceSummary: ReportResponse = {
        ...mockReport,
        summary: '   \n  \t  ',
      };

      render(<ReportView report={reportWithWhitespaceSummary} />);
      expect(screen.getByText('No executive summary provided.')).toBeInTheDocument();
    });
  });

  describe('Empty Report State', () => {
    it('renders default empty placeholder card and guidance when report is null and no shiftKey provided', () => {
      render(<ReportView report={null} />);

      expect(screen.getByRole('status')).toBeInTheDocument();
      expect(screen.getByText('No handover report generated for this shift yet.')).toBeInTheDocument();
      expect(
        screen.getByText("Log shift events and click 'Generate Handover' to create a synthesized report.")
      ).toBeInTheDocument();
    });

    it('includes shiftKey in empty state message when shiftKey prop is provided', () => {
      render(<ReportView report={null} shiftKey="2026-11-14-night" />);

      expect(screen.getByText('No report generated for shift 2026-11-14-night.')).toBeInTheDocument();
      expect(
        screen.getByText("Log shift events and click 'Generate Handover' to create a synthesized report.")
      ).toBeInTheDocument();
    });
  });

  describe('Loading State & Skeleton Layout', () => {
    it('renders accessible loading container with aria-busy="true" and skeleton placeholder elements', () => {
      render(<ReportView isLoading={true} />);

      const loadingContainer = screen.getByRole('status');
      expect(loadingContainer).toHaveAttribute('aria-busy', 'true');
      expect(loadingContainer).toHaveAttribute('aria-label', 'Loading handover report...');
      expect(screen.getByText('Loading handover report...')).toBeInTheDocument();

      // Skeletons mirroring layout
      expect(screen.getByTestId('report-skeleton-metadata')).toBeInTheDocument();
      expect(screen.getByTestId('report-skeleton-summary')).toBeInTheDocument();
      expect(screen.getByTestId('report-skeleton-safety')).toBeInTheDocument();
      expect(screen.getByTestId('report-skeleton-actions')).toBeInTheDocument();
    });
  });

  describe('Error State & Retry Action', () => {
    it('renders standard Error message in alert banner', () => {
      const error = new Error('Database connection timed out');
      render(<ReportView error={error} />);

      const alert = screen.getByRole('alert');
      expect(alert).toBeInTheDocument();
      expect(screen.getByText('Failed to load handover report')).toBeInTheDocument();
      expect(screen.getByText('Database connection timed out')).toBeInTheDocument();
    });

    it('renders RFC 9457 Problem Details message and traceId when ApiError is passed', () => {
      const apiError = new ApiError(502, 'Bad Gateway', {
        type: 'https://api.copilot.plant/errors/upstream-unavailable',
        title: 'Bad Gateway',
        status: 502,
        detail: 'Gemini inference gateway returned an invalid response.',
        traceId: 'abcd1234efgh5678ijkl9012mnop3456',
      });

      render(<ReportView error={apiError} />);

      const alert = screen.getByRole('alert');
      expect(alert).toBeInTheDocument();
      expect(screen.getByText('Gemini inference gateway returned an invalid response.')).toBeInTheDocument();
      expect(screen.getByText('Trace ID: abcd1234efgh5678ijkl9012mnop3456')).toBeInTheDocument();
    });

    it('renders Retry button when onRetry is provided and triggers callback on click', async () => {
      const user = userEvent.setup();
      const onRetryMock = vi.fn();
      render(<ReportView error={new Error('Network error')} onRetry={onRetryMock} />);

      const retryBtn = screen.getByRole('button', { name: /Retry/i });
      expect(retryBtn).toBeInTheDocument();

      await user.click(retryBtn);
      expect(onRetryMock).toHaveBeenCalledTimes(1);
    });

    it('supports keyboard activation (Enter and Space) on the Retry button', async () => {
      const user = userEvent.setup();
      const onRetryMock = vi.fn();
      render(<ReportView error={new Error('Network error')} onRetry={onRetryMock} />);

      const retryBtn = screen.getByRole('button', { name: /Retry/i });
      retryBtn.focus();
      expect(retryBtn).toHaveFocus();

      await user.keyboard('{Enter}');
      expect(onRetryMock).toHaveBeenCalledTimes(1);

      await user.keyboard(' ');
      expect(onRetryMock).toHaveBeenCalledTimes(2);
    });
  });

  describe('Safe Text Escaping (Strict Zero XSS)', () => {
    it('escapes raw HTML tags in summary, safetyNotes, and openActions without executing or creating DOM elements', () => {
      const maliciousReport: ReportResponse = {
        id: 'xss-test-uuid',
        shiftKey: '<b onmouseover=alert(1)>2026-11-14-early</b>',
        version: 1,
        summary: '<script>alert("XSS in summary")</script><img src=x onerror=alert(1) /><b>bold text</b>',
        safetyNotes: [
          '<script>alert("XSS in safety")</script>',
          '<svg onload=alert(2)><circle cx="5" cy="5" r="5"/></svg>',
        ],
        openActions: [
          {
            priority: 'high',
            action: '<a href="javascript:alert(3)">Click here for free supervisor prize</a>',
            owner: '<span style="color:red">Hacker</span>',
          },
        ],
        modelUsed: '<iframe src="evil.com"></iframe>',
        eventCount: 1,
        createdAt: '2026-11-14T10:00:00Z',
      };

      const { container } = render(<ReportView report={maliciousReport} />);

      // Verify NO malicious DOM elements were created
      expect(container.querySelector('script')).toBeNull();
      expect(container.querySelector('iframe')).toBeNull();
      expect(container.querySelector('img')).toBeNull();
      expect(container.querySelector('b')).toBeNull();
      expect(container.querySelector('a')).toBeNull();
      expect(container.querySelector('svg[onload]')).toBeNull();

      // Verify the content is rendered purely as literal plain text strings
      expect(
        screen.getByText('<script>alert("XSS in summary")</script><img src=x onerror=alert(1) /><b>bold text</b>')
      ).toBeInTheDocument();

      expect(screen.getByText('<script>alert("XSS in safety")</script>')).toBeInTheDocument();
      expect(screen.getByText('<svg onload=alert(2)><circle cx="5" cy="5" r="5"/></svg>')).toBeInTheDocument();

      expect(
        screen.getByText('<a href="javascript:alert(3)">Click here for free supervisor prize</a>')
      ).toBeInTheDocument();
      expect(screen.getByText('<span style="color:red">Hacker</span>')).toBeInTheDocument();
      expect(screen.getByText('<iframe src="evil.com"></iframe>')).toBeInTheDocument();
      expect(screen.getByText('<b onmouseover=alert(1)>2026-11-14-early</b>')).toBeInTheDocument();
    });
  });

  describe('Defensive & Malformed Data Handling', () => {
    it('renders cleanly without crashing when safetyNotes is undefined or null', () => {
      const malformedReport = {
        ...mockReport,
        safetyNotes: null as unknown as string[],
      };

      render(<ReportView report={malformedReport} />);
      expect(screen.getByText('No safety incidents or hazards flagged for this shift.')).toBeInTheDocument();
    });

    it('renders cleanly without crashing when openActions is undefined or null', () => {
      const malformedReport = {
        ...mockReport,
        openActions: null as unknown as OpenAction[],
      };

      render(<ReportView report={malformedReport} />);
      expect(screen.getByText('No open action items pending for oncoming shift.')).toBeInTheDocument();
    });

    it('safely handles invalid date format in createdAt without crashing', () => {
      const reportWithInvalidDate: ReportResponse = {
        ...mockReport,
        createdAt: 'not-a-valid-date-string',
      };

      render(<ReportView report={reportWithInvalidDate} />);
      expect(screen.getByText('not-a-valid-date-string')).toBeInTheDocument();
    });

    it('applies custom className to the root container', () => {
      const { container } = render(<ReportView report={mockReport} className="custom-test-class" />);
      expect(container.firstChild).toHaveClass('custom-test-class');
    });
  });
});
