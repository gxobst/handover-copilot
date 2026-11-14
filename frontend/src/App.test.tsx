import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import App from './App';
import { eventsApi, reportsApi } from './services';
import { ApiError } from './services/errors';

describe('App Component & Shell Integration', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(eventsApi, 'listEvents').mockResolvedValue([]);
    vi.spyOn(reportsApi, 'listReports').mockResolvedValue([]);
  });

  describe('Smoke Tests', () => {
    it('renders the application title/heading successfully', async () => {
      await act(async () => {
        render(<App />);
      });

      const heading = screen.getByRole('heading', {
        level: 1,
        name: /shift handover copilot/i,
      });
      expect(heading).toBeInTheDocument();

      const titleText = screen.getByText('Shift Handover Copilot');
      expect(titleText).toBeInTheDocument();
    });

    it('renders design system category badges', async () => {
      await act(async () => {
        render(<App />);
      });

      expect(screen.getByText('downtime')).toBeInTheDocument();
      expect(screen.getByText('quality')).toBeInTheDocument();
      expect(screen.getByText('safety')).toBeInTheDocument();
      expect(screen.getByText('info')).toBeInTheDocument();
    });
  });

  describe('Full Handover Workflow Component Integration', () => {
    it('renders shift selector, event form, event list, generate button, and report view on the shift board', async () => {
      await act(async () => {
        render(<App />);
      });

      // ShiftSelector date input and shift type radios are present
      expect(screen.getByLabelText(/shift date/i)).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /early shift/i })).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /late shift/i })).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /night shift/i })).toBeInTheDocument();

      // EventForm machine input and submit button are present
      expect(screen.getByPlaceholderText(/e\.g\. press-01/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /log event/i })).toBeInTheDocument();

      // EventList category filter buttons and empty state are present
      expect(screen.getByRole('button', { name: /all \(0\)/i })).toBeInTheDocument();
      expect(screen.getByText(/no events logged for this shift/i)).toBeInTheDocument();

      // GenerateButton is present
      expect(screen.getByRole('button', { name: /generate shift handover report/i })).toBeInTheDocument();

      // ReportView empty/initial state is present
      expect(screen.getByText(/no report generated/i)).toBeInTheDocument();

      // AdminPanelTrigger is present
      expect(screen.getByRole('button', { name: /admin settings/i })).toBeInTheDocument();
    });

    it('opens and closes AdminPanel when clicking AdminPanelTrigger', async () => {
      await act(async () => {
        render(<App />);
      });

      // Admin panel dialog should not be visible initially
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

      // Click Admin Settings trigger button
      const adminTrigger = screen.getByRole('button', { name: /admin settings/i });
      fireEvent.click(adminTrigger);

      // Admin panel dialog is now open
      const dialog = await screen.findByRole('dialog');
      expect(dialog).toBeInTheDocument();
      expect(screen.getByText(/admin configuration panel/i)).toBeInTheDocument();

      // Close the admin panel
      const closeButton = screen.getByRole('button', { name: /close admin panel/i });
      fireEvent.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });

    it('switches between Shift Board and Report History tabs seamlessly', async () => {
      await act(async () => {
        render(<App />);
      });

      // Currently on Shift Board
      expect(screen.getByPlaceholderText(/e\.g\. press-01/i)).toBeInTheDocument();

      // Click Report History tab
      const historyTab = screen.getByRole('button', { name: /report history/i });
      fireEvent.click(historyTab);

      // Report History view is rendered
      expect(await screen.findByRole('heading', { name: 'Report History' })).toBeInTheDocument();
      expect(screen.queryByPlaceholderText(/e\.g\. press-01/i)).not.toBeInTheDocument();

      // Switch back to Shift Board
      const boardTab = screen.getByRole('button', { name: /shift board/i });
      fireEvent.click(boardTab);

      expect(await screen.findByPlaceholderText(/e\.g\. press-01/i)).toBeInTheDocument();
    });

    it('wires ToastProvider and ToastContainer into App and displays error toast on action error', async () => {
      vi.spyOn(eventsApi, 'createEvent').mockRejectedValue(
        new ApiError(500, 'Internal Server Error', {
          type: 'about:blank',
          title: 'Database Failure',
          status: 500,
          detail: 'Database write failed',
          traceId: 'app-trace-12345',
        })
      );

      await act(async () => {
        render(<App />);
      });

      // Fill in event form and submit
      const machineInput = screen.getByPlaceholderText(/e\.g\. press-01/i);
      const noteInput = screen.getByPlaceholderText(/describe the incident/i);
      const submitButton = screen.getByRole('button', { name: /log event/i });

      fireEvent.change(machineInput, { target: { value: 'Press-01' } });
      fireEvent.change(noteInput, { target: { value: 'Hydraulic leak detected' } });

      await act(async () => {
        fireEvent.click(submitButton);
      });

      // ToastContainer notifications region should display the error toast with traceId
      const notificationRegion = await screen.findByRole('region', { name: /notifications/i });
      expect(notificationRegion).toBeInTheDocument();
      expect(within(notificationRegion).getByRole('alert')).toBeInTheDocument();
      expect(within(notificationRegion).getByText('Database Failure')).toBeInTheDocument();
      expect(within(notificationRegion).getByText('Database write failed')).toBeInTheDocument();
      expect(within(notificationRegion).getByTestId('trace-id-value')).toHaveTextContent('app-trace-12345');
    });
  });
});
