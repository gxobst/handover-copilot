import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GenerateButton } from './GenerateButton';
import { reportsApi } from '../services';
import { ApiError } from '../services/errors';
import type { ReportResponse } from '../types/api';

describe('GenerateButton Component', () => {
  const validShiftKey = '2026-11-14-early';

  const mockReport: ReportResponse = {
    id: '2cff7f41-1053-4548-a6f5-153fc558a04d',
    shiftKey: validShiftKey,
    version: 1,
    summary: 'Press-01 experienced a 45-minute outage due to hydraulic pressure loss. Shift completed smoothly.',
    openActions: [
      {
        action: 'Monitor hydraulic oil pressure on Press-01',
        priority: 'high',
        owner: 'Mechanical Maintenance',
      },
    ],
    safetyNotes: ['Verify hydraulic fluid levels before startup.'],
    modelUsed: 'google/gemini-2.5-flash',
    eventCount: 3,
    createdAt: '2026-11-14T14:30:00Z',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  describe('Initial & Default Button Presentation', () => {
    it('renders enabled "Generate Handover" button with Sparkles icon when eventCount >= 1 and shiftKey is valid', () => {
      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      expect(button).toBeInTheDocument();
      expect(button).toHaveTextContent('Generate Handover');
      expect(button).not.toBeDisabled();
      expect(button.className).toContain('bg-slate-900');
      expect(button.className).toContain('text-white');
      expect(screen.queryByRole('note')).not.toBeInTheDocument();
    });

    it('renders "Regenerate Handover" button when hasExistingReport={true}', () => {
      render(
        <GenerateButton
          shiftKey={validShiftKey}
          eventCount={3}
          hasExistingReport={true}
        />
      );

      const button = screen.getByRole('button', { name: /regenerate shift handover report/i });
      expect(button).toBeInTheDocument();
      expect(button).toHaveTextContent('Regenerate Handover');
      expect(button).not.toBeDisabled();
    });

    it('renders "Regenerate Handover" button when currentVersion > 0', () => {
      render(
        <GenerateButton
          shiftKey={validShiftKey}
          eventCount={3}
          currentVersion={2}
        />
      );

      const button = screen.getByRole('button', { name: /regenerate shift handover report/i });
      expect(button).toBeInTheDocument();
      expect(button).toHaveTextContent('Regenerate Handover');
    });

    it('applies custom className when provided', () => {
      const { container } = render(
        <GenerateButton
          shiftKey={validShiftKey}
          eventCount={3}
          className="custom-button-wrapper"
        />
      );

      expect(container.firstChild).toHaveClass('custom-button-wrapper');
    });
  });

  describe('Zero-Events Disabled Guard (AC-6)', () => {
    it('disables the button and renders helper message when eventCount === 0', () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport');

      render(<GenerateButton shiftKey={validShiftKey} eventCount={0} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute('aria-disabled', 'true');
      expect(button).toHaveAttribute('aria-describedby', 'generate-zero-events-helper');

      const helper = screen.getByRole('note');
      expect(helper).toBeInTheDocument();
      expect(helper).toHaveAttribute('id', 'generate-zero-events-helper');
      expect(helper).toHaveTextContent(
        'At least 1 shift event is required to generate a handover report.'
      );

      // Attempted clicks do not dispatch API calls
      fireEvent.click(button);
      expect(generateSpy).not.toHaveBeenCalled();
    });

    it('blocks keyboard activations when eventCount === 0', () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport');

      render(<GenerateButton shiftKey={validShiftKey} eventCount={0} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.keyDown(button, { key: 'Enter', code: 'Enter' });
      fireEvent.keyDown(button, { key: ' ', code: 'Space' });

      expect(generateSpy).not.toHaveBeenCalled();
    });
  });

  describe('Invalid or Missing ShiftKey Guard', () => {
    it('disables the button and displays warning when shiftKey is empty', () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport');

      render(<GenerateButton shiftKey="" eventCount={5} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute('aria-describedby', 'generate-shift-warning');

      const warning = screen.getByRole('note');
      expect(warning).toBeInTheDocument();
      expect(warning).toHaveAttribute('id', 'generate-shift-warning');
      expect(warning).toHaveTextContent('Select a valid shift before generating a report.');

      fireEvent.click(button);
      expect(generateSpy).not.toHaveBeenCalled();
    });

    it('disables the button when shiftKey format is invalid', () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport');

      render(<GenerateButton shiftKey="invalid-shift-key" eventCount={5} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      expect(button).toBeDisabled();

      const warning = screen.getByRole('note');
      expect(warning).toHaveTextContent('Select a valid shift before generating a report.');

      fireEvent.click(button);
      expect(generateSpy).not.toHaveBeenCalled();
    });

    it('disables the button when shiftKey contains an invalid calendar date', () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport');

      render(<GenerateButton shiftKey="2026-02-31-early" eventCount={5} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      expect(button).toBeDisabled();

      const warning = screen.getByRole('note');
      expect(warning).toHaveTextContent('Select a valid shift before generating a report.');

      fireEvent.click(button);
      expect(generateSpy).not.toHaveBeenCalled();
    });
  });

  describe('External Disabled Prop', () => {
    it('disables the button when disabled prop is true', () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport');

      render(<GenerateButton shiftKey={validShiftKey} eventCount={5} disabled={true} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      expect(button).toBeDisabled();

      fireEvent.click(button);
      expect(generateSpy).not.toHaveBeenCalled();
    });
  });

  describe('Click Submission & Concurrency Guard', () => {
    it('dispatches reportsApi.generateReport with shiftKey when clicked', async () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport').mockResolvedValue(mockReport);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={2} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      expect(generateSpy).toHaveBeenCalledTimes(1);
      expect(generateSpy).toHaveBeenCalledWith({ shiftKey: validShiftKey });
    });

    it('transitions to in-flight state with spinner and "Generating Handover..." text while request is pending', async () => {
      let resolvePromise: (value: ReportResponse) => void = () => {};
      const pendingPromise = new Promise<ReportResponse>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(reportsApi, 'generateReport').mockReturnValue(pendingPromise);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={2} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      // In-flight expectations
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute('aria-busy', 'true');
      expect(button).toHaveTextContent('Generating Handover...');

      // Complete request
      await act(async () => {
        resolvePromise(mockReport);
      });

      expect(button).not.toBeDisabled();
      expect(button).not.toHaveAttribute('aria-busy');
    });

    it('blocks rapid duplicate clicks so that only a single API request is dispatched', async () => {
      let resolvePromise: (value: ReportResponse) => void = () => {};
      const pendingPromise = new Promise<ReportResponse>((res) => {
        resolvePromise = res;
      });
      const generateSpy = vi.spyOn(reportsApi, 'generateReport').mockReturnValue(pendingPromise);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={2} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });

      // Click rapidly multiple times
      fireEvent.click(button);
      fireEvent.click(button);
      fireEvent.click(button);

      expect(generateSpy).toHaveBeenCalledTimes(1);

      await act(async () => {
        resolvePromise(mockReport);
      });

      expect(generateSpy).toHaveBeenCalledTimes(1);
    });
  });

  describe('Cold-Start Progress UX (AC-3, plan.md §6.5, design-system.md §3.3)', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it('cleans up fast response timer when resolving in < 3000ms so cold-start banner never appears', async () => {
      let resolvePromise: (value: ReportResponse) => void = () => {};
      const fastPromise = new Promise<ReportResponse>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(reportsApi, 'generateReport').mockReturnValue(fastPromise);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      // Advance by 2500ms (< 3000ms)
      act(() => {
        vi.advanceTimersByTime(2500);
      });
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      expect(screen.queryByText(/waking up the database/i)).not.toBeInTheDocument();

      // Resolve response before 3000ms
      await act(async () => {
        resolvePromise(mockReport);
      });

      // Advance clock past 3000ms to verify banner still never appears
      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.queryByText(/waking up the database/i)).not.toBeInTheDocument();
    });

    it('displays high-contrast cold-start notification with elapsed ticker after 3000ms in-flight', async () => {
      let resolvePromise: (value: ReportResponse) => void = () => {};
      const longPromise = new Promise<ReportResponse>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(reportsApi, 'generateReport').mockReturnValue(longPromise);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      // Advance to 2900ms: banner not yet visible
      act(() => {
        vi.advanceTimersByTime(2900);
      });
      expect(screen.queryByText(/waking up the database/i)).not.toBeInTheDocument();

      // Advance past 3000ms: banner appears with exact text and 3s elapsed
      act(() => {
        vi.advanceTimersByTime(200);
      });

      const coldStartBanner = screen.getByRole('status');
      expect(coldStartBanner).toBeInTheDocument();
      expect(coldStartBanner).toHaveAttribute('aria-live', 'polite');
      expect(
        screen.getByText(
          'Waking up the database — the first request after an idle period may take up to 20 s.'
        )
      ).toBeInTheDocument();
      expect(screen.getByText('Elapsed: 3s')).toBeInTheDocument();

      // Advance by 1 second: counter increments to 4s
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByText('Elapsed: 4s')).toBeInTheDocument();

      // Advance by another 2 seconds: counter increments to 6s
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(screen.getByText('Elapsed: 6s')).toBeInTheDocument();

      // Resolve request: cold-start banner is immediately removed
      await act(async () => {
        resolvePromise(mockReport);
      });

      expect(screen.queryByText(/waking up the database/i)).not.toBeInTheDocument();
    });

    it('cleanly destroys timers on unmount without throwing errors', () => {
      const longPromise = new Promise<ReportResponse>(() => {});
      vi.spyOn(reportsApi, 'generateReport').mockReturnValue(longPromise);

      const { unmount } = render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      act(() => {
        vi.advanceTimersByTime(3500);
      });
      expect(screen.getByText(/waking up the database/i)).toBeInTheDocument();

      // Unmount while running
      expect(() => unmount()).not.toThrow();

      // Advancing timers after unmount causes no errors
      expect(() => {
        act(() => {
          vi.advanceTimersByTime(5000);
        });
      }).not.toThrow();
    });
  });

  describe('Successful Generation Handling (AC-3, AC-5)', () => {
    it('clears in-flight state, updates button label to "Regenerate Handover", shows success banner, and invokes onReportGenerated', async () => {
      vi.spyOn(reportsApi, 'generateReport').mockResolvedValue(mockReport);
      const handleGenerated = vi.fn();

      render(
        <GenerateButton
          shiftKey={validShiftKey}
          eventCount={3}
          onReportGenerated={handleGenerated}
        />
      );

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      // onReportGenerated callback called
      expect(handleGenerated).toHaveBeenCalledTimes(1);
      expect(handleGenerated).toHaveBeenCalledWith(mockReport);

      // Button label updated to Regenerate Handover
      expect(button).toHaveTextContent('Regenerate Handover');
      expect(button).not.toBeDisabled();

      // Success banner rendered
      const successBanner = screen.getByRole('status');
      expect(successBanner).toBeInTheDocument();
      expect(successBanner).toHaveTextContent(
        `Handover report v${mockReport.version} generated successfully.`
      );
    });

    it('auto-dismisses success banner after 5 seconds', async () => {
      vi.useFakeTimers();
      vi.spyOn(reportsApi, 'generateReport').mockResolvedValue(mockReport);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      expect(
        screen.getByText(`Handover report v${mockReport.version} generated successfully.`)
      ).toBeInTheDocument();

      // Advance by 5000ms: success banner auto-clears
      act(() => {
        vi.advanceTimersByTime(5000);
      });

      expect(
        screen.queryByText(`Handover report v${mockReport.version} generated successfully.`)
      ).not.toBeInTheDocument();
    });
  });

  describe('Error Handling & RFC 9457 Problem Details (AC-6, AC-8)', () => {
    it('handles HTTP 422 error by displaying API detail and trace ID', async () => {
      const apiError = new ApiError(422, 'Unprocessable Entity', {
        type: 'https://api.shift-copilot.example.com/errors/validation',
        title: 'Unprocessable Entity',
        status: 422,
        detail: 'No events found for shift.',
        traceId: 'tr-422-zero-events',
      });
      vi.spyOn(reportsApi, 'generateReport').mockRejectedValue(apiError);
      const handleError = vi.fn();

      render(
        <GenerateButton
          shiftKey={validShiftKey}
          eventCount={3}
          onError={handleError}
        />
      );

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      // Error banner
      const alert = screen.getByRole('alert');
      expect(alert).toBeInTheDocument();
      expect(alert).toHaveAttribute('aria-live', 'assertive');
      expect(screen.getByText('No events found for shift.')).toBeInTheDocument();
      expect(screen.getByText('Trace ID: tr-422-zero-events')).toBeInTheDocument();

      // onError called
      expect(handleError).toHaveBeenCalledTimes(1);
      expect(handleError).toHaveBeenCalledWith(apiError);

      // Button returns to enabled state
      expect(button).not.toBeDisabled();
    });

    it('handles HTTP 502 error by displaying LLM unavailable message, detail, and trace ID', async () => {
      const apiError = new ApiError(502, 'Bad Gateway', {
        type: 'https://api.shift-copilot.example.com/errors/llm-failure',
        title: 'Bad Gateway',
        status: 502,
        detail: 'Both primary Gemini 2.5 Flash and fallback 1.5 Pro models exhausted quota.',
        traceId: 'tr-502-llm-exhausted',
      });
      vi.spyOn(reportsApi, 'generateReport').mockRejectedValue(apiError);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      expect(
        screen.getByText('Report generation failed: LLM models unavailable. Please try again.')
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          'Both primary Gemini 2.5 Flash and fallback 1.5 Pro models exhausted quota.'
        )
      ).toBeInTheDocument();
      expect(screen.getByText('Trace ID: tr-502-llm-exhausted')).toBeInTheDocument();
    });

    it('handles HTTP 429 error by displaying rate limit warning', async () => {
      const apiError = new ApiError(429, 'Too Many Requests', {
        type: 'about:blank',
        title: 'Too Many Requests',
        status: 429,
        detail: 'Quota exceeded for report generation.',
      });
      vi.spyOn(reportsApi, 'generateReport').mockRejectedValue(apiError);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      expect(
        screen.getByText('Rate limit exceeded. Please wait a few moments before trying again.')
      ).toBeInTheDocument();
    });

    it('handles network failure by displaying connection guidance', async () => {
      const networkError = new TypeError('Failed to fetch');
      vi.spyOn(reportsApi, 'generateReport').mockRejectedValue(networkError);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      expect(
        screen.getByText(
          'Unable to connect to the handover generation service. Check your connection or server status.'
        )
      ).toBeInTheDocument();
    });

    it('allows operator to retry generation by clicking "Try Again"', async () => {
      const generateSpy = vi
        .spyOn(reportsApi, 'generateReport')
        .mockRejectedValueOnce(new Error('Network glitch'))
        .mockResolvedValueOnce(mockReport);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const mainButton = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(mainButton);

      await act(async () => {
        await Promise.resolve();
      });

      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(generateSpy).toHaveBeenCalledTimes(1);

      // Click "Try Again"
      const retryButton = screen.getByRole('button', { name: /try again/i });
      fireEvent.click(retryButton);

      await act(async () => {
        await Promise.resolve();
      });

      expect(generateSpy).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(
        screen.getByText(`Handover report v${mockReport.version} generated successfully.`)
      ).toBeInTheDocument();
    });

    it('allows operator to copy trace ID to clipboard', async () => {
      vi.useFakeTimers();
      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, {
        clipboard: {
          writeText: writeTextMock,
        },
      });

      const apiError = new ApiError(500, 'Internal Server Error', {
        type: 'about:blank',
        title: 'Error',
        status: 500,
        detail: 'Database write collision.',
        traceId: 'tr-clipboard-12345',
      });
      vi.spyOn(reportsApi, 'generateReport').mockRejectedValue(apiError);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      const copyButton = screen.getByRole('button', { name: /copy trace id/i });
      expect(copyButton).toBeInTheDocument();
      expect(copyButton).toHaveTextContent('Copy');

      // Click copy button
      await act(async () => {
        fireEvent.click(copyButton);
      });

      expect(writeTextMock).toHaveBeenCalledWith('tr-clipboard-12345');
      expect(copyButton).toHaveTextContent('Copied!');

      // Reverts after 2000ms
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(copyButton).toHaveTextContent('Copy');
    });
  });

  describe('Props & State Synchronization', () => {
    it('resets error and success states when shiftKey changes', async () => {
      vi.spyOn(reportsApi, 'generateReport').mockResolvedValue(mockReport);

      const { rerender } = render(
        <GenerateButton shiftKey={validShiftKey} eventCount={3} />
      );

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      expect(
        screen.getByText(`Handover report v${mockReport.version} generated successfully.`)
      ).toBeInTheDocument();

      // Change shiftKey
      rerender(<GenerateButton shiftKey="2026-11-14-late" eventCount={3} />);

      expect(
        screen.queryByText(`Handover report v${mockReport.version} generated successfully.`)
      ).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /generate shift handover report/i })).toHaveTextContent(
        'Generate Handover'
      );
    });
  });

  describe('Keyboard Accessibility & Security', () => {
    it('activates generation via Enter key when focused and enabled', async () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport').mockResolvedValue(mockReport);
      const user = userEvent.setup();

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      button.focus();
      expect(button).toHaveFocus();

      await user.keyboard('{Enter}');

      await act(async () => {
        await Promise.resolve();
      });

      expect(generateSpy).toHaveBeenCalledTimes(1);
    });

    it('activates generation via Space key when focused and enabled', async () => {
      const generateSpy = vi.spyOn(reportsApi, 'generateReport').mockResolvedValue(mockReport);
      const user = userEvent.setup();

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      button.focus();
      expect(button).toHaveFocus();

      await user.keyboard(' ');

      await act(async () => {
        await Promise.resolve();
      });

      expect(generateSpy).toHaveBeenCalledTimes(1);
    });

    it('safely escapes HTML characters in error descriptions without using dangerouslySetInnerHTML', async () => {
      const maliciousScript = '<img src=x onerror="alert(\'XSS\')" />';
      const apiError = new ApiError(422, 'Unprocessable Entity', {
        type: 'about:blank',
        title: 'Validation Error',
        status: 422,
        detail: maliciousScript,
      });
      vi.spyOn(reportsApi, 'generateReport').mockRejectedValue(apiError);

      render(<GenerateButton shiftKey={validShiftKey} eventCount={3} />);

      const button = screen.getByRole('button', { name: /generate shift handover report/i });
      fireEvent.click(button);

      await act(async () => {
        await Promise.resolve();
      });

      // The text is rendered as literal text node, not an HTML tag
      const alert = screen.getByRole('alert');
      expect(alert).toHaveTextContent(maliciousScript);
      expect(document.querySelector('img')).toBeNull();
    });
  });
});
