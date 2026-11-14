import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EventForm } from './EventForm';
import { eventsApi } from '../services';
import { ApiError } from '../services/errors';
import type { EventResponse } from '../types';

describe('EventForm Component', () => {
  const validShiftKey = '2026-11-14-early';

  const mockCreatedEvent: EventResponse = {
    id: '41f34ec4-f489-4362-869d-9555cd9c0f98',
    shiftKey: validShiftKey,
    machine: 'Press-01',
    category: 'downtime',
    note: 'Hydraulic pressure dropped suddenly, main stamping line stopped for 45 minutes.',
    createdAt: '2026-11-14T06:45:00Z',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  describe('Initial Rendering & Accessibility', () => {
    it('renders all required form controls with correct labels and placeholders', () => {
      render(<EventForm shiftKey={validShiftKey} />);

      // Machine input
      const machineInput = screen.getByLabelText(/machine \/ station/i);
      expect(machineInput).toBeInTheDocument();
      expect(machineInput).toHaveAttribute('id', 'machine');
      expect(machineInput).toHaveAttribute('name', 'machine');
      expect(machineInput).toHaveAttribute('placeholder', 'e.g. Press-01, Conveyor-B');
      expect(machineInput).toHaveValue('');

      // Category selector group
      const categoryGroup = screen.getByRole('radiogroup', { name: /category/i });
      expect(categoryGroup).toBeInTheDocument();

      const downtimeRadio = screen.getByRole('radio', { name: /downtime/i });
      const qualityRadio = screen.getByRole('radio', { name: /quality/i });
      const safetyRadio = screen.getByRole('radio', { name: /safety/i });
      const infoRadio = screen.getByRole('radio', { name: /info/i });

      expect(downtimeRadio).toBeInTheDocument();
      expect(qualityRadio).toBeInTheDocument();
      expect(safetyRadio).toBeInTheDocument();
      expect(infoRadio).toBeInTheDocument();

      // Note textarea
      const noteInput = screen.getByLabelText(/event note/i);
      expect(noteInput).toBeInTheDocument();
      expect(noteInput).toHaveAttribute('id', 'note');
      expect(noteInput).toHaveAttribute('name', 'note');
      expect(noteInput).toHaveAttribute(
        'placeholder',
        'Describe the incident, stoppage reason, or observation...'
      );
      expect(noteInput).toHaveValue('');

      // Character counter
      const charCounter = screen.getByTestId('char-counter');
      expect(charCounter).toHaveTextContent('0 / 2000');

      // Submit button
      const submitBtn = screen.getByRole('button', { name: /log event/i });
      expect(submitBtn).toBeInTheDocument();
      expect(submitBtn).toHaveAttribute('type', 'submit');
      expect(submitBtn).not.toBeDisabled();
    });

    it('defaults category selection to downtime with active indicator', () => {
      render(<EventForm shiftKey={validShiftKey} />);

      const downtimeRadio = screen.getByRole('radio', { name: /downtime/i });
      const qualityRadio = screen.getByRole('radio', { name: /quality/i });

      expect(downtimeRadio).toHaveAttribute('aria-checked', 'true');
      expect(qualityRadio).toHaveAttribute('aria-checked', 'false');

      // Active styling includes ring highlight
      expect(downtimeRadio.className).toContain('ring-2');
      expect(downtimeRadio.className).toContain('font-bold');
    });

    it('renders high-contrast design-system badge colors for all category buttons', () => {
      render(<EventForm shiftKey={validShiftKey} />);

      const downtimeRadio = screen.getByRole('radio', { name: /downtime/i });
      const qualityRadio = screen.getByRole('radio', { name: /quality/i });
      const safetyRadio = screen.getByRole('radio', { name: /safety/i });
      const infoRadio = screen.getByRole('radio', { name: /info/i });

      // Downtime: bg-amber-100 text-amber-800 border-amber-300
      expect(downtimeRadio.className).toContain('bg-amber-100');
      expect(downtimeRadio.className).toContain('text-amber-800');
      expect(downtimeRadio.className).toContain('border-amber-300');

      // Quality: bg-purple-100 text-purple-800 border-purple-300
      expect(qualityRadio.className).toContain('bg-purple-100');
      expect(qualityRadio.className).toContain('text-purple-800');
      expect(qualityRadio.className).toContain('border-purple-300');

      // Safety: bg-red-100 text-red-800 border-red-300 font-semibold
      expect(safetyRadio.className).toContain('bg-red-100');
      expect(safetyRadio.className).toContain('text-red-800');
      expect(safetyRadio.className).toContain('border-red-300');
      expect(safetyRadio.className).toContain('font-semibold');

      // Info: bg-slate-100 text-slate-800 border-slate-300
      expect(infoRadio.className).toContain('bg-slate-100');
      expect(infoRadio.className).toContain('text-slate-800');
      expect(infoRadio.className).toContain('border-slate-300');
    });
  });

  describe('ShiftKey Validation', () => {
    it('renders warning banner and disables submit button when shiftKey is empty', () => {
      render(<EventForm shiftKey="" />);

      expect(
        screen.getByText('A valid shift must be selected before logging events')
      ).toBeInTheDocument();

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      expect(submitBtn).toBeDisabled();
    });

    it('renders warning banner and disables submit button when shiftKey is malformed', () => {
      render(<EventForm shiftKey="invalid-shift-id" />);

      expect(
        screen.getByText('A valid shift must be selected before logging events')
      ).toBeInTheDocument();

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      expect(submitBtn).toBeDisabled();
    });

    it('does not render warning banner when shiftKey is valid', () => {
      render(<EventForm shiftKey="2026-11-14-night" />);

      expect(
        screen.queryByText('A valid shift must be selected before logging events')
      ).not.toBeInTheDocument();

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      expect(submitBtn).not.toBeDisabled();
    });
  });

  describe('Client-Side Form Validation', () => {
    it('blocks submission and shows inline error when machine name is empty', async () => {
      const createSpy = vi.spyOn(eventsApi, 'createEvent');
      render(<EventForm shiftKey={validShiftKey} />);

      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(noteInput, { target: { value: 'Valid note description' } });

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      fireEvent.click(submitBtn);

      expect(createSpy).not.toHaveBeenCalled();
      expect(screen.getByText('Machine name is required')).toBeInTheDocument();

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      expect(machineInput).toHaveAttribute('aria-invalid', 'true');
      expect(machineInput).toHaveAttribute('aria-describedby', 'machine-error');
    });

    it('blocks submission and shows inline error when machine name is whitespace only', async () => {
      const createSpy = vi.spyOn(eventsApi, 'createEvent');
      render(<EventForm shiftKey={validShiftKey} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      fireEvent.change(machineInput, { target: { value: '   ' } });

      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(noteInput, { target: { value: 'Valid note description' } });

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      fireEvent.click(submitBtn);

      expect(createSpy).not.toHaveBeenCalled();
      expect(screen.getByText('Machine name is required')).toBeInTheDocument();
    });

    it('blocks submission and shows inline error when note is empty', async () => {
      const createSpy = vi.spyOn(eventsApi, 'createEvent');
      render(<EventForm shiftKey={validShiftKey} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      fireEvent.change(machineInput, { target: { value: 'Press-01' } });

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      fireEvent.click(submitBtn);

      expect(createSpy).not.toHaveBeenCalled();
      expect(screen.getByText('Note is required')).toBeInTheDocument();

      const noteInput = screen.getByLabelText(/event note/i);
      expect(noteInput).toHaveAttribute('aria-invalid', 'true');
      expect(noteInput).toHaveAttribute('aria-describedby', 'note-error');
    });

    it('blocks submission and shows inline error when note is whitespace only', async () => {
      const createSpy = vi.spyOn(eventsApi, 'createEvent');
      render(<EventForm shiftKey={validShiftKey} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      fireEvent.change(machineInput, { target: { value: 'Press-01' } });

      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(noteInput, { target: { value: '   \n  \t ' } });

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      fireEvent.click(submitBtn);

      expect(createSpy).not.toHaveBeenCalled();
      expect(screen.getByText('Note is required')).toBeInTheDocument();
    });

    it('clears inline validation errors as user types into the fields', async () => {
      render(<EventForm shiftKey={validShiftKey} />);

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      fireEvent.click(submitBtn);

      expect(screen.getByText('Machine name is required')).toBeInTheDocument();
      expect(screen.getByText('Note is required')).toBeInTheDocument();

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      fireEvent.change(machineInput, { target: { value: 'P' } });
      expect(screen.queryByText('Machine name is required')).not.toBeInTheDocument();

      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(noteInput, { target: { value: 'N' } });
      expect(screen.queryByText('Note is required')).not.toBeInTheDocument();
    });
  });

  describe('Character Counter & Limits', () => {
    it('updates character counter synchronously as user types', () => {
      render(<EventForm shiftKey={validShiftKey} />);

      const noteInput = screen.getByLabelText(/event note/i);
      const charCounter = screen.getByTestId('char-counter');

      fireEvent.change(noteInput, { target: { value: 'Motor overheating' } });
      expect(charCounter).toHaveTextContent('17 / 2000');
      expect(charCounter.className).toContain('text-slate-500');
    });

    it('applies amber warning styling when character count exceeds 1900', () => {
      render(<EventForm shiftKey={validShiftKey} />);

      const noteInput = screen.getByLabelText(/event note/i);
      const charCounter = screen.getByTestId('char-counter');

      const longText = 'a'.repeat(1905);
      fireEvent.change(noteInput, { target: { value: longText } });

      expect(charCounter).toHaveTextContent('1905 / 2000');
      expect(charCounter.className).toContain('text-amber-600');
    });

    it('applies red danger styling at 2000 characters and enforces maximum length', () => {
      render(<EventForm shiftKey={validShiftKey} />);

      const noteInput = screen.getByLabelText(/event note/i);
      const charCounter = screen.getByTestId('char-counter');

      const maxText = 'a'.repeat(2000);
      fireEvent.change(noteInput, { target: { value: maxText } });

      expect(charCounter).toHaveTextContent('2000 / 2000');
      expect(charCounter.className).toContain('text-red-600');
      expect(charCounter.className).toContain('font-bold');

      // Attempting to exceed 2000 chars is blocked
      const overflowText = 'a'.repeat(2010);
      fireEvent.change(noteInput, { target: { value: overflowText } });

      expect(noteInput).toHaveValue(maxText);
      expect(charCounter).toHaveTextContent('2000 / 2000');
    });
  });

  describe('Category Selection', () => {
    it('selecting a different category updates active state and sends correct category in payload', async () => {
      const createSpy = vi.spyOn(eventsApi, 'createEvent').mockResolvedValue(mockCreatedEvent);
      const user = userEvent.setup();

      render(<EventForm shiftKey={validShiftKey} />);

      const qualityRadio = screen.getByRole('radio', { name: /quality/i });
      const downtimeRadio = screen.getByRole('radio', { name: /downtime/i });

      await user.click(qualityRadio);

      expect(qualityRadio).toHaveAttribute('aria-checked', 'true');
      expect(downtimeRadio).toHaveAttribute('aria-checked', 'false');

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(machineInput, { target: { value: 'Press-02' } });
      fireEvent.change(noteInput, { target: { value: 'Scratch on finished surface' } });

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      await user.click(submitBtn);

      expect(createSpy).toHaveBeenCalledWith({
        shiftKey: validShiftKey,
        machine: 'Press-02',
        category: 'quality',
        note: 'Scratch on finished surface',
      });
    });

    it('can select safety and info categories', async () => {
      const createSpy = vi.spyOn(eventsApi, 'createEvent').mockResolvedValue(mockCreatedEvent);
      const user = userEvent.setup();

      render(<EventForm shiftKey={validShiftKey} />);

      const safetyRadio = screen.getByRole('radio', { name: /safety/i });
      await user.click(safetyRadio);
      expect(safetyRadio).toHaveAttribute('aria-checked', 'true');

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(machineInput, { target: { value: 'Line-4' } });
      fireEvent.change(noteInput, { target: { value: 'Emergency stop tested' } });

      await user.click(screen.getByRole('button', { name: /log event/i }));

      expect(createSpy).toHaveBeenCalledWith({
        shiftKey: validShiftKey,
        machine: 'Line-4',
        category: 'safety',
        note: 'Emergency stop tested',
      });
    });
  });

  describe('Submission, Loading States, & Success Handling', () => {
    it('dispatches trimmed inputs, resets form fields, displays success message, and calls onEventCreated', async () => {
      const createSpy = vi.spyOn(eventsApi, 'createEvent').mockResolvedValue(mockCreatedEvent);
      const handleCreated = vi.fn();

      render(<EventForm shiftKey={validShiftKey} onEventCreated={handleCreated} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);

      fireEvent.change(machineInput, { target: { value: '  Press-01   ' } });
      fireEvent.change(noteInput, { target: { value: '   Hydraulic failure   ' } });

      fireEvent.click(screen.getByRole('button', { name: /log event/i }));

      await act(async () => {
        await Promise.resolve();
      });

      // Dispatched trimmed values
      expect(createSpy).toHaveBeenCalledTimes(1);
      expect(createSpy).toHaveBeenCalledWith({
        shiftKey: validShiftKey,
        machine: 'Press-01',
        category: 'downtime',
        note: 'Hydraulic failure',
      });

      // Inputs reset
      expect(machineInput).toHaveValue('');
      expect(noteInput).toHaveValue('');
      expect(screen.getByTestId('char-counter')).toHaveTextContent('0 / 2000');

      // Success message displayed
      expect(screen.getByText('Event logged successfully')).toBeInTheDocument();
      expect(handleCreated).toHaveBeenCalledWith(mockCreatedEvent);
    });

    it('shows loading spinner and disables all controls while submission is in-flight', async () => {
      let resolvePromise: (value: EventResponse) => void = () => {};
      const pendingPromise = new Promise<EventResponse>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(eventsApi, 'createEvent').mockReturnValue(pendingPromise);

      render(<EventForm shiftKey={validShiftKey} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(machineInput, { target: { value: 'Conveyor-A' } });
      fireEvent.change(noteInput, { target: { value: 'Belt alignment issue' } });

      const submitBtn = screen.getByRole('button', { name: /log event/i });
      fireEvent.click(submitBtn);

      // Verify in-flight state
      expect(screen.getByText('Logging...')).toBeInTheDocument();
      expect(submitBtn).toBeDisabled();
      expect(machineInput).toBeDisabled();
      expect(noteInput).toBeDisabled();
      expect(screen.getByRole('radio', { name: /downtime/i })).toBeDisabled();

      // Resolve API request
      await act(async () => {
        resolvePromise(mockCreatedEvent);
      });

      // Returns to idle state
      expect(screen.queryByText('Logging...')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /log event/i })).toBeInTheDocument();
      expect(machineInput).not.toBeDisabled();
      expect(noteInput).not.toBeDisabled();
    });

    it('blocks rapid duplicate submissions while an existing request is in-flight', async () => {
      let resolvePromise: (value: EventResponse) => void = () => {};
      const pendingPromise = new Promise<EventResponse>((res) => {
        resolvePromise = res;
      });
      const createSpy = vi.spyOn(eventsApi, 'createEvent').mockReturnValue(pendingPromise);

      render(<EventForm shiftKey={validShiftKey} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(machineInput, { target: { value: 'Conveyor-A' } });
      fireEvent.change(noteInput, { target: { value: 'Belt alignment issue' } });

      const submitBtn = screen.getByRole('button', { name: /log event/i });

      // Simulate rapid double click
      fireEvent.click(submitBtn);
      fireEvent.click(submitBtn);
      fireEvent.click(submitBtn);

      expect(createSpy).toHaveBeenCalledTimes(1);

      await act(async () => {
        resolvePromise(mockCreatedEvent);
      });
    });
  });

  describe('Cold-Start Alert Behavior', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it('displays persistent cold-start notification after 3 seconds in-flight and clears upon completion', async () => {
      let resolvePromise: (value: EventResponse) => void = () => {};
      const pendingPromise = new Promise<EventResponse>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(eventsApi, 'createEvent').mockReturnValue(pendingPromise);

      render(<EventForm shiftKey={validShiftKey} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(machineInput, { target: { value: 'Press-01' } });
      fireEvent.change(noteInput, { target: { value: 'Motor overheating' } });

      fireEvent.click(screen.getByRole('button', { name: /log event/i }));

      // Before 3000ms: no cold start banner
      act(() => {
        vi.advanceTimersByTime(2900);
      });
      expect(
        screen.queryByText(/waking up the database/i)
      ).not.toBeInTheDocument();

      // At 3000ms: cold start banner appears
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(
        screen.getByText(/waking up the database — the first request after an idle period may take up to 20 s\./i)
      ).toBeInTheDocument();

      // Resolve request: banner disappears
      await act(async () => {
        resolvePromise(mockCreatedEvent);
      });
      expect(
        screen.queryByText(/waking up the database/i)
      ).not.toBeInTheDocument();
    });

    it('does not display cold-start banner if request resolves before 3 seconds', async () => {
      let resolvePromise: (value: EventResponse) => void = () => {};
      const fastPromise = new Promise<EventResponse>((res) => {
        resolvePromise = res;
      });
      vi.spyOn(eventsApi, 'createEvent').mockReturnValue(fastPromise);

      render(<EventForm shiftKey={validShiftKey} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);
      fireEvent.change(machineInput, { target: { value: 'Press-01' } });
      fireEvent.change(noteInput, { target: { value: 'Motor overheating' } });

      fireEvent.click(screen.getByRole('button', { name: /log event/i }));

      act(() => {
        vi.advanceTimersByTime(1000);
      });

      await act(async () => {
        resolvePromise(mockCreatedEvent);
      });

      act(() => {
        vi.advanceTimersByTime(3000);
      });

      expect(
        screen.queryByText(/waking up the database/i)
      ).not.toBeInTheDocument();
    });
  });

  describe('Error Handling & Input Preservation', () => {
    it('preserves user input, renders RFC 9457 error details with trace ID, and calls onError on rejection', async () => {
      const apiError = new ApiError(422, 'Unprocessable Entity', {
        type: 'https://api.shift-copilot.example.com/errors/validation',
        title: 'Validation Error',
        status: 422,
        detail: 'Machine Press-01 is currently decommissioned.',
        traceId: 'trace-test-uuid-999',
      });

      vi.spyOn(eventsApi, 'createEvent').mockRejectedValue(apiError);
      const handleError = vi.fn();

      render(<EventForm shiftKey={validShiftKey} onError={handleError} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);

      fireEvent.change(machineInput, { target: { value: 'Press-01' } });
      fireEvent.change(noteInput, { target: { value: 'Pressure test failed' } });

      fireEvent.click(screen.getByRole('button', { name: /log event/i }));

      await act(async () => {
        await Promise.resolve();
      });

      // Inputs preserved
      expect(machineInput).toHaveValue('Press-01');
      expect(noteInput).toHaveValue('Pressure test failed');

      // Error message and trace ID rendered
      expect(
        screen.getByText('Machine Press-01 is currently decommissioned.')
      ).toBeInTheDocument();
      expect(screen.getByText('Trace ID: trace-test-uuid-999')).toBeInTheDocument();

      // onError called
      expect(handleError).toHaveBeenCalledTimes(1);
      expect(handleError).toHaveBeenCalledWith(apiError);
    });

    it('handles generic native Error rejection and preserves user input', async () => {
      const nativeError = new Error('Network connection timeout');
      vi.spyOn(eventsApi, 'createEvent').mockRejectedValue(nativeError);
      const handleError = vi.fn();

      render(<EventForm shiftKey={validShiftKey} onError={handleError} />);

      const machineInput = screen.getByLabelText(/machine \/ station/i);
      const noteInput = screen.getByLabelText(/event note/i);

      fireEvent.change(machineInput, { target: { value: 'Robot-Arm-2' } });
      fireEvent.change(noteInput, { target: { value: 'Gripper calibration error' } });

      fireEvent.click(screen.getByRole('button', { name: /log event/i }));

      await act(async () => {
        await Promise.resolve();
      });

      expect(machineInput).toHaveValue('Robot-Arm-2');
      expect(noteInput).toHaveValue('Gripper calibration error');
      expect(screen.getByText('Network connection timeout')).toBeInTheDocument();
      expect(handleError).toHaveBeenCalledWith(nativeError);
    });
  });

  describe('Disabled Prop', () => {
    it('disables all inputs, buttons, and submissions when disabled prop is true', () => {
      render(<EventForm shiftKey={validShiftKey} disabled={true} />);

      expect(screen.getByLabelText(/machine \/ station/i)).toBeDisabled();
      expect(screen.getByLabelText(/event note/i)).toBeDisabled();
      expect(screen.getByRole('radio', { name: /downtime/i })).toBeDisabled();
      expect(screen.getByRole('radio', { name: /quality/i })).toBeDisabled();
      expect(screen.getByRole('radio', { name: /safety/i })).toBeDisabled();
      expect(screen.getByRole('radio', { name: /info/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /log event/i })).toBeDisabled();
    });
  });
});
