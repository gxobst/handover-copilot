import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { ErrorToast } from './ErrorToast';
import { ToastContainer } from './ToastContainer';
import { ToastProvider, useToast, type ToastMessage } from '../context/ToastContext';
import { ApiError } from '../services/errors';

// Helper component to trigger useToast actions in tests
const TestConsumer: React.FC<{
  onReady?: (actions: ReturnType<typeof useToast>) => void;
}> = ({ onReady }) => {
  const toastActions = useToast();

  React.useEffect(() => {
    if (onReady) {
      onReady(toastActions);
    }
  }, [onReady, toastActions]);

  return (
    <div>
      <button
        onClick={() => toastActions.showError(new Error('Sample error'))}
      >
        Trigger Error
      </button>
    </div>
  );
};

describe('ErrorToast Component & ToastContext System', () => {
  const mockTraceId = '4bf92f3577b34da6a3ce929d0e0e4736';

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('RFC 9457 ProblemDetails Rendering', () => {
    it('renders RFC 9457 ProblemDetails with title, detail, HTTP status badge, and copyable trace ID', () => {
      const mockToast: ToastMessage = {
        id: 'toast-1',
        createdAt: Date.now(),
        title: 'Unprocessable Entity',
        detail: 'The provided shift parameters were rejected.',
        status: 422,
        traceId: mockTraceId,
      };

      const handleDismiss = vi.fn();
      render(<ErrorToast toast={mockToast} onDismiss={handleDismiss} />);

      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 3, name: 'Unprocessable Entity' })).toBeInTheDocument();
      expect(screen.getByText('The provided shift parameters were rejected.')).toBeInTheDocument();
      expect(screen.getByTestId('status-badge')).toHaveTextContent('422');
      expect(screen.getByTestId('trace-id-value')).toHaveTextContent(mockTraceId);
      expect(screen.getByRole('button', { name: /copy trace id/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /dismiss error notification/i })).toBeInTheDocument();
    });

    it('omits trace ID section cleanly when traceId is undefined or empty', () => {
      const mockToast: ToastMessage = {
        id: 'toast-2',
        createdAt: Date.now(),
        title: 'Network Error',
        detail: 'Connection timed out',
        status: 504,
      };

      render(<ErrorToast toast={mockToast} onDismiss={vi.fn()} />);

      expect(screen.queryByText(/Trace ID:/i)).not.toBeInTheDocument();
      expect(screen.queryByTestId('trace-id-value')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /copy trace id/i })).not.toBeInTheDocument();
    });

    it('omits HTTP status badge when status is undefined or 0', () => {
      const mockToast: ToastMessage = {
        id: 'toast-3',
        createdAt: Date.now(),
        title: 'Network Error',
        detail: 'Unable to connect to server',
        status: 0,
      };

      render(<ErrorToast toast={mockToast} onDismiss={vi.fn()} />);

      expect(screen.queryByTestId('status-badge')).not.toBeInTheDocument();
    });
  });

  describe('Trace ID One-Click Copy Behavior', () => {
    it('calls navigator.clipboard.writeText with exact trace ID and toggles copied state indicator', async () => {
      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, {
        clipboard: {
          writeText: writeTextMock,
        },
      });

      const mockToast: ToastMessage = {
        id: 'toast-copy-1',
        createdAt: Date.now(),
        title: 'Internal Server Error',
        detail: 'Database unreachable',
        traceId: mockTraceId,
      };

      render(<ErrorToast toast={mockToast} onDismiss={vi.fn()} />);

      const copyButton = screen.getByRole('button', { name: /copy trace id/i });
      fireEvent.click(copyButton);

      expect(writeTextMock).toHaveBeenCalledWith(mockTraceId);

      // Copied state visual indicator appears
      expect(await screen.findByText('Copied!')).toBeInTheDocument();
    });

    it('handles clipboard write failure gracefully without unhandled promise rejections', async () => {
      const writeTextMock = vi.fn().mockRejectedValue(new Error('Permission denied'));
      Object.assign(navigator, {
        clipboard: {
          writeText: writeTextMock,
        },
      });

      const mockToast: ToastMessage = {
        id: 'toast-copy-fail',
        createdAt: Date.now(),
        title: 'Error',
        detail: 'Sample detail',
        traceId: mockTraceId,
      };

      render(<ErrorToast toast={mockToast} onDismiss={vi.fn()} />);

      const copyButton = screen.getByRole('button', { name: /copy trace id/i });
      fireEvent.click(copyButton);

      expect(await screen.findByText('Copy failed')).toBeInTheDocument();
    });
  });

  describe('Manual Dismissal and Keyboard Accessibility', () => {
    it('clicking X close button triggers onDismiss immediately', () => {
      const handleDismiss = vi.fn();
      const mockToast: ToastMessage = {
        id: 'toast-manual-dismiss',
        createdAt: Date.now(),
        title: 'Bad Gateway',
        detail: 'Upstream gateway timed out',
      };

      render(<ErrorToast toast={mockToast} onDismiss={handleDismiss} />);

      const closeButton = screen.getByRole('button', { name: /dismiss error notification/i });
      fireEvent.click(closeButton);

      expect(handleDismiss).toHaveBeenCalledWith('toast-manual-dismiss');
    });

    it('pressing Escape while an element inside toast is focused dismisses the toast', () => {
      const handleDismiss = vi.fn();
      const mockToast: ToastMessage = {
        id: 'toast-escape',
        createdAt: Date.now(),
        title: 'Error',
        detail: 'Press Escape to close',
        traceId: mockTraceId,
      };

      render(<ErrorToast toast={mockToast} onDismiss={handleDismiss} />);

      const alertContainer = screen.getByRole('alert');
      fireEvent.keyDown(alertContainer, { key: 'Escape', code: 'Escape' });

      expect(handleDismiss).toHaveBeenCalledWith('toast-escape');
    });
  });

  describe('Safe Text Rendering', () => {
    it('renders malicious HTML/script strings in detail and title as plain text without execution', () => {
      const maliciousTitle = '<img src=x onerror=alert(1)>Malicious Title';
      const maliciousDetail = '<script>window.pwned=true;</script><b>Harmful Detail</b>';

      const mockToast: ToastMessage = {
        id: 'toast-xss',
        createdAt: Date.now(),
        title: maliciousTitle,
        detail: maliciousDetail,
      };

      render(<ErrorToast toast={mockToast} onDismiss={vi.fn()} />);

      expect(screen.getByText(maliciousTitle)).toBeInTheDocument();
      expect(screen.getByText(maliciousDetail)).toBeInTheDocument();
      expect(document.querySelector('script')).toBeNull();
      expect(document.querySelector('img')).toBeNull();
    });
  });

  describe('Auto-Dismissal & Pause-on-Hover / Focus Timers', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('auto-dismisses toast after 8000ms by default', () => {
      const handleDismiss = vi.fn();
      const mockToast: ToastMessage = {
        id: 'toast-timer-1',
        createdAt: Date.now(),
        title: 'Timeout Test',
        detail: 'Should dismiss in 8s',
      };

      render(<ErrorToast toast={mockToast} onDismiss={handleDismiss} />);

      expect(handleDismiss).not.toHaveBeenCalled();

      // Advance clock by 7999ms
      act(() => {
        vi.advanceTimersByTime(7999);
      });
      expect(handleDismiss).not.toHaveBeenCalled();

      // Advance by remaining 1ms (total 8000ms)
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(handleDismiss).toHaveBeenCalledWith('toast-timer-1');
    });

    it('pause-on-hover: hovering pauses timer and mouseLeave resumes countdown', () => {
      const handleDismiss = vi.fn();
      const mockToast: ToastMessage = {
        id: 'toast-hover-1',
        createdAt: Date.now(),
        title: 'Hover Test',
        detail: 'Hover should pause auto-dismiss',
      };

      render(<ErrorToast toast={mockToast} onDismiss={handleDismiss} />);

      // Let 3000ms elapse
      act(() => {
        vi.advanceTimersByTime(3000);
      });

      const alertCard = screen.getByRole('alert');

      // Hover over toast
      fireEvent.mouseEnter(alertCard);

      // Advance time by 10000ms while hovered
      act(() => {
        vi.advanceTimersByTime(10000);
      });
      expect(handleDismiss).not.toHaveBeenCalled();

      // Mouse leaves toast - countdown resumes with remaining ~5000ms
      fireEvent.mouseLeave(alertCard);

      act(() => {
        vi.advanceTimersByTime(4900);
      });
      expect(handleDismiss).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(handleDismiss).toHaveBeenCalledWith('toast-hover-1');
    });

    it('pause-on-focus: focusing inside toast pauses timer and blur resumes countdown', () => {
      const handleDismiss = vi.fn();
      const mockToast: ToastMessage = {
        id: 'toast-focus-1',
        createdAt: Date.now(),
        title: 'Focus Test',
        detail: 'Focus should pause auto-dismiss',
      };

      render(<ErrorToast toast={mockToast} onDismiss={handleDismiss} />);

      // Let 2000ms elapse
      act(() => {
        vi.advanceTimersByTime(2000);
      });

      const alertCard = screen.getByRole('alert');
      const closeButton = screen.getByRole('button', { name: /dismiss error notification/i });

      // Focus inside toast
      fireEvent.focus(closeButton);

      // Advance 12000ms while focused
      act(() => {
        vi.advanceTimersByTime(12000);
      });
      expect(handleDismiss).not.toHaveBeenCalled();

      // Blur out of toast
      fireEvent.blur(alertCard, { relatedTarget: document.body });

      // Remaining ~6000ms must run
      act(() => {
        vi.advanceTimersByTime(5900);
      });
      expect(handleDismiss).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(handleDismiss).toHaveBeenCalledWith('toast-focus-1');
    });
  });

  describe('ToastContext & ToastContainer Integration', () => {
    it('throws error when useToast is used outside of ToastProvider', () => {
      // Suppress console.error in Vitest for expected uncaught error
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      expect(() => {
        render(<TestConsumer />);
      }).toThrow('useToast must be used within a ToastProvider');

      consoleSpy.mockRestore();
    });

    it('renders ToastContainer with role="region" and aria-label="Notifications"', () => {
      let actions!: ReturnType<typeof useToast>;

      render(
        <ToastProvider>
          <TestConsumer onReady={(a) => (actions = a)} />
          <ToastContainer />
        </ToastProvider>
      );

      // Initially no toasts, ToastContainer returns null
      expect(screen.queryByRole('region', { name: 'Notifications' })).not.toBeInTheDocument();

      // Add a toast
      act(() => {
        actions.showToast({
          title: 'Container Test',
          detail: 'Container visibility test',
        });
      });

      const region = screen.getByRole('region', { name: 'Notifications' });
      expect(region).toBeInTheDocument();
      expect(region).toHaveClass('fixed', 'bottom-4', 'right-4');
    });

    it('enforces maximum 5 toasts queue cap and evicts oldest toast when 7 are dispatched', () => {
      let actions!: ReturnType<typeof useToast>;

      render(
        <ToastProvider>
          <TestConsumer onReady={(a) => (actions = a)} />
          <ToastContainer />
        </ToastProvider>
      );

      act(() => {
        for (let i = 1; i <= 7; i++) {
          actions.showError(`Error message ${i}`);
        }
      });

      // Errors 1 and 2 should have been evicted
      expect(screen.queryByText('Error message 1')).not.toBeInTheDocument();
      expect(screen.queryByText('Error message 2')).not.toBeInTheDocument();

      // Errors 3 through 7 should be visible (total 5)
      expect(screen.getByText('Error message 3')).toBeInTheDocument();
      expect(screen.getByText('Error message 4')).toBeInTheDocument();
      expect(screen.getByText('Error message 5')).toBeInTheDocument();
      expect(screen.getByText('Error message 6')).toBeInTheDocument();
      expect(screen.getByText('Error message 7')).toBeInTheDocument();

      expect(actions.toasts.length).toBe(5);
    });

    it('showError normalizes ApiError instance with populated traceId', () => {
      let actions!: ReturnType<typeof useToast>;

      render(
        <ToastProvider>
          <TestConsumer onReady={(a) => (actions = a)} />
          <ToastContainer />
        </ToastProvider>
      );

      const apiError = new ApiError(500, 'Internal Server Error', {
        type: 'https://example.com/probs/internal',
        title: 'Backend Database Failure',
        status: 500,
        detail: 'Postgres connection pool exhausted',
        traceId: '1234567890abcdef1234567890abcdef',
      });

      act(() => {
        actions.showError(apiError);
      });

      expect(screen.getByText('Backend Database Failure')).toBeInTheDocument();
      expect(screen.getByText('Postgres connection pool exhausted')).toBeInTheDocument();
      expect(screen.getByTestId('status-badge')).toHaveTextContent('500');
      expect(screen.getByTestId('trace-id-value')).toHaveTextContent('1234567890abcdef1234567890abcdef');
    });

    it('showError normalizes generic native Error with "Application Error" default title', () => {
      let actions!: ReturnType<typeof useToast>;

      render(
        <ToastProvider>
          <TestConsumer onReady={(a) => (actions = a)} />
          <ToastContainer />
        </ToastProvider>
      );

      act(() => {
        actions.showError(new Error('Calculation failed'));
      });

      expect(screen.getByText('Application Error')).toBeInTheDocument();
      expect(screen.getByText('Calculation failed')).toBeInTheDocument();
    });

    it('showError normalizes plain string error with "Error" default title', () => {
      let actions!: ReturnType<typeof useToast>;

      render(
        <ToastProvider>
          <TestConsumer onReady={(a) => (actions = a)} />
          <ToastContainer />
        </ToastProvider>
      );

      act(() => {
        actions.showError('Something broke on the client');
      });

      expect(screen.getByText('Error')).toBeInTheDocument();
      expect(screen.getByText('Something broke on the client')).toBeInTheDocument();
    });

    it('showError normalizes null/undefined with "Unknown Error" fallback', () => {
      let actions!: ReturnType<typeof useToast>;

      render(
        <ToastProvider>
          <TestConsumer onReady={(a) => (actions = a)} />
          <ToastContainer />
        </ToastProvider>
      );

      act(() => {
        actions.showError(null);
      });

      expect(screen.getByText('Unknown Error')).toBeInTheDocument();
      expect(screen.getByText('An unexpected error occurred.')).toBeInTheDocument();
    });

    it('showError extracts snake_case trace_id correctly', () => {
      let actions!: ReturnType<typeof useToast>;

      render(
        <ToastProvider>
          <TestConsumer onReady={(a) => (actions = a)} />
          <ToastContainer />
        </ToastProvider>
      );

      act(() => {
        actions.showError({
          title: 'Custom Problem',
          detail: 'Problem with snake_case trace_id',
          status: 400,
          trace_id: 'snake_trace_1234567890abcdef',
        });
      });

      expect(screen.getByText('Custom Problem')).toBeInTheDocument();
      expect(screen.getByTestId('trace-id-value')).toHaveTextContent('snake_trace_1234567890abcdef');
    });

    it('dismissToast removes specific toast and clearToasts clears all', () => {
      let actions!: ReturnType<typeof useToast>;

      render(
        <ToastProvider>
          <TestConsumer onReady={(a) => (actions = a)} />
          <ToastContainer />
        </ToastProvider>
      );

      let id1 = '';
      let id2 = '';

      act(() => {
        id1 = actions.showError('Error One');
        id2 = actions.showError('Error Two');
      });

      expect(id1).toBeTruthy();
      expect(id2).toBeTruthy();
      expect(screen.getByText('Error One')).toBeInTheDocument();
      expect(screen.getByText('Error Two')).toBeInTheDocument();

      act(() => {
        actions.dismissToast(id1);
      });

      expect(screen.queryByText('Error One')).not.toBeInTheDocument();
      expect(screen.getByText('Error Two')).toBeInTheDocument();

      act(() => {
        actions.clearToasts();
      });

      expect(screen.queryByText('Error Two')).not.toBeInTheDocument();
      expect(actions.toasts.length).toBe(0);
    });
  });
});
