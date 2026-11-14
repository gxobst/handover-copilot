import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ReportDetail } from './ReportDetail';
import { ApiError } from '../services/errors';
import type { ReportResponse } from '../types/api';

describe('ReportDetail Component', () => {
  const mockReport: ReportResponse = {
    id: '11111111-1111-1111-1111-111111111111',
    shiftKey: '2026-11-14-early',
    version: 1,
    summary: 'Press-01 was down for 30 minutes due to sensor malfunction. Normal operations resumed.',
    openActions: [
      {
        action: 'Inspect temperature sensor on Press-01',
        priority: 'high',
        owner: 'Alice Electrician',
      },
      {
        action: 'Review shift logs',
        priority: 'low',
        owner: 'Bob Supervisor',
      },
    ],
    safetyNotes: ['Lockout/tagout protocol followed during sensor replacement.'],
    modelUsed: 'google/gemini-3.5-flash-lite',
    eventCount: 4,
    createdAt: '2026-11-14T14:30:00Z',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders loading skeleton when isLoading is true', () => {
    render(<ReportDetail isLoading={true} />);

    expect(screen.getByTestId('report-detail-loading')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
  });

  it('renders empty state card when report is null and not loading', () => {
    render(<ReportDetail report={null} />);

    expect(screen.getByTestId('report-detail-empty')).toBeInTheDocument();
    expect(screen.getByText('No report snapshot selected')).toBeInTheDocument();
    expect(
      screen.getByText('Select a report version from the history list to inspect its snapshot details.')
    ).toBeInTheDocument();
  });

  it('renders full immutable report snapshot content when report is provided', () => {
    render(<ReportDetail report={mockReport} />);

    expect(screen.getByTestId('report-detail')).toBeInTheDocument();
    expect(screen.getByText('Executive Summary')).toBeInTheDocument();
    expect(
      screen.getByText('Press-01 was down for 30 minutes due to sensor malfunction. Normal operations resumed.')
    ).toBeInTheDocument();
    expect(screen.getByText('Safety Notes')).toBeInTheDocument();
    expect(
      screen.getByText('Lockout/tagout protocol followed during sensor replacement.')
    ).toBeInTheDocument();
    expect(screen.getByText('Open Actions')).toBeInTheDocument();
    expect(screen.getByText('Inspect temperature sensor on Press-01')).toBeInTheDocument();
    expect(screen.getByText('Alice Electrician')).toBeInTheDocument();
  });

  it('renders historical version snapshot banner when isHistorical is true', () => {
    render(<ReportDetail report={mockReport} isHistorical={true} />);

    const banner = screen.getByTestId('historical-version-banner');
    expect(banner).toBeInTheDocument();
    expect(
      screen.getByText('Historical Version 1 Snapshot (Read-Only / Immutable)')
    ).toBeInTheDocument();
    expect(
      screen.getByText(/This snapshot reflects the exact report content synthesized for shift/i)
    ).toBeInTheDocument();
  });

  it('does not render historical banner when isHistorical is false', () => {
    render(<ReportDetail report={mockReport} isHistorical={false} />);

    expect(screen.queryByTestId('historical-version-banner')).not.toBeInTheDocument();
  });

  it('renders RFC 9457 error card with trace ID, copy button, and retry action', () => {
    const onRetryMock = vi.fn();
    const error = new ApiError(500, 'Internal Server Error', {
      type: 'about:blank',
      title: 'Internal Server Error',
      status: 500,
      detail: 'Database query timed out',
      traceId: 'trace-999-xyz',
    });

    render(<ReportDetail error={error} onRetry={onRetryMock} />);

    const errorAlert = screen.getByTestId('report-detail-error');
    expect(errorAlert).toBeInTheDocument();
    expect(errorAlert).toHaveAttribute('role', 'alert');
    expect(screen.getByText('Internal Server Error')).toBeInTheDocument();
    expect(screen.getByText('Database query timed out')).toBeInTheDocument();
    expect(screen.getByText('Trace ID: trace-999-xyz')).toBeInTheDocument();

    const retryButton = screen.getByRole('button', { name: /try again/i });
    fireEvent.click(retryButton);
    expect(onRetryMock).toHaveBeenCalledTimes(1);
  });

  it('displays "Report snapshot not found" when error is HTTP 404', () => {
    const error = new ApiError(404, 'Not Found', {
      type: 'about:blank',
      title: 'Not Found',
      status: 404,
      detail: 'Report snapshot does not exist',
      traceId: 'trace-404-notfound',
    });

    render(<ReportDetail error={error} />);

    expect(screen.getByText('Report snapshot not found')).toBeInTheDocument();
    expect(screen.getByText('Report snapshot does not exist')).toBeInTheDocument();
    expect(screen.getByText('Trace ID: trace-404-notfound')).toBeInTheDocument();
  });

  it('handles clipboard copy of trace ID', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    const error = new ApiError(500, 'Internal Error', {
      type: 'about:blank',
      title: 'Internal Error',
      status: 500,
      detail: 'Server failure',
      traceId: 'trace-copy-123',
    });
    render(<ReportDetail error={error} />);

    const copyBtn = screen.getByRole('button', { name: /copy trace id/i });
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith('trace-copy-123');
    expect(screen.getByText('Copied!')).toBeInTheDocument();
  });

  it('renders safely without throwing when report has empty safetyNotes and openActions', () => {
    const sparseReport: ReportResponse = {
      id: '22222222-2222-2222-2222-222222222222',
      shiftKey: '2026-11-14-early',
      version: 2,
      summary: 'Smooth shift, no events logged.',
      openActions: [],
      safetyNotes: [],
      modelUsed: 'google/gemini-3.5-flash-lite',
      eventCount: 0,
      createdAt: '2026-11-14T15:00:00Z',
    };

    render(<ReportDetail report={sparseReport} />);

    expect(screen.getByText('Smooth shift, no events logged.')).toBeInTheDocument();
    expect(screen.getByText('No safety incidents or hazards flagged for this shift.')).toBeInTheDocument();
    expect(screen.getByText('No open action items pending for oncoming shift.')).toBeInTheDocument();
  });

  it('strictly protects against XSS by rendering malicious strings as plain text', () => {
    const maliciousReport: ReportResponse = {
      id: '33333333-3333-3333-3333-333333333333',
      shiftKey: '2026-11-14-early',
      version: 1,
      summary: '<script>alert("xss")</script><img src=x onerror=alert(1)>',
      openActions: [
        {
          action: '<b onmouseover=alert("action")>Malicious Action</b>',
          priority: 'high',
          owner: '<iframe src="javascript:alert(1)">Owner</iframe>',
        },
      ],
      safetyNotes: ['<script>document.cookie</script>'],
      modelUsed: 'google/gemini-3.5-flash-lite',
      eventCount: 1,
      createdAt: '2026-11-14T16:00:00Z',
    };

    const { container } = render(<ReportDetail report={maliciousReport} />);

    expect(screen.getByText('<script>alert("xss")</script><img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(screen.getByText('<b onmouseover=alert("action")>Malicious Action</b>')).toBeInTheDocument();
    expect(screen.getByText('<iframe src="javascript:alert(1)">Owner</iframe>')).toBeInTheDocument();
    expect(screen.getByText('<script>document.cookie</script>')).toBeInTheDocument();

    expect(container.querySelectorAll('script').length).toBe(0);
    expect(container.querySelectorAll('iframe').length).toBe(0);
  });
});
