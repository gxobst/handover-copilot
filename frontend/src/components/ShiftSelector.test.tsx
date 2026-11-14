import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ShiftSelector } from './ShiftSelector';
import { getLocalDateString } from '../utils/shiftKey';

describe('ShiftSelector Component', () => {
  const today = getLocalDateString();

  describe('Rendering & Defaults', () => {
    it('renders with default today date and early shift when value prop is omitted', () => {
      const handleChange = vi.fn();
      render(<ShiftSelector onChange={handleChange} />);

      // Label and date input
      const dateInput = screen.getByLabelText(/shift date/i);
      expect(dateInput).toBeInTheDocument();
      expect(dateInput).toHaveValue(today);

      // Monospace badge showing active shiftKey
      const badge = screen.getByTestId('shift-key-badge');
      expect(badge).toHaveTextContent(`${today}-early`);

      // Segmented control buttons
      const earlyRadio = screen.getByRole('radio', { name: /early shift/i });
      const lateRadio = screen.getByRole('radio', { name: /late shift/i });
      const nightRadio = screen.getByRole('radio', { name: /night shift/i });

      expect(earlyRadio).toHaveAttribute('aria-checked', 'true');
      expect(lateRadio).toHaveAttribute('aria-checked', 'false');
      expect(nightRadio).toHaveAttribute('aria-checked', 'false');

      // Quick buttons
      expect(screen.getByRole('button', { name: /today/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /previous day/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /next day/i })).toBeInTheDocument();
    });

    it('renders with the initial parsed value when a valid value prop is supplied', () => {
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-late" onChange={handleChange} />);

      const dateInput = screen.getByLabelText(/shift date/i);
      expect(dateInput).toHaveValue('2026-11-14');

      const lateRadio = screen.getByRole('radio', { name: /late shift/i });
      expect(lateRadio).toHaveAttribute('aria-checked', 'true');

      const badge = screen.getByTestId('shift-key-badge');
      expect(badge).toHaveTextContent('2026-11-14-late');
    });

    it('applies high-contrast styling to active shift button and neutral styling to inactive buttons', () => {
      render(<ShiftSelector value="2026-11-14-night" onChange={vi.fn()} />);

      const nightRadio = screen.getByRole('radio', { name: /night shift/i });
      const earlyRadio = screen.getByRole('radio', { name: /early shift/i });

      // Active styling
      expect(nightRadio.className).toContain('bg-slate-900');
      expect(nightRadio.className).toContain('text-white');

      // Inactive styling
      expect(earlyRadio.className).toContain('bg-white');
      expect(earlyRadio.className).toContain('text-slate-700');
    });
  });

  describe('Shift Type Selection', () => {
    it('clicking an inactive shift button updates active shift state and invokes onChange preserving current date', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-early" onChange={handleChange} />);

      const lateRadio = screen.getByRole('radio', { name: /late shift/i });
      await user.click(lateRadio);

      expect(handleChange).toHaveBeenCalledTimes(1);
      expect(handleChange).toHaveBeenCalledWith('2026-11-14-late');
      expect(lateRadio).toHaveAttribute('aria-checked', 'true');
      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent('2026-11-14-late');
    });

    it('clicking an already active shift button is a no-op', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-early" onChange={handleChange} />);

      const earlyRadio = screen.getByRole('radio', { name: /early shift/i });
      await user.click(earlyRadio);

      expect(handleChange).not.toHaveBeenCalled();
      expect(earlyRadio).toHaveAttribute('aria-checked', 'true');
    });
  });

  describe('Date Input Changes', () => {
    it('changing date input invokes onChange preserving current shift type', () => {
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-night" onChange={handleChange} />);

      const dateInput = screen.getByLabelText(/shift date/i);
      fireEvent.change(dateInput, { target: { value: '2026-11-20' } });

      expect(handleChange).toHaveBeenCalledTimes(1);
      expect(handleChange).toHaveBeenCalledWith('2026-11-20-night');
      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent('2026-11-20-night');
    });

    it('clearing date input suppresses onChange and displays inline validation error', () => {
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-early" onChange={handleChange} />);

      const dateInput = screen.getByLabelText(/shift date/i);
      fireEvent.change(dateInput, { target: { value: '' } });

      expect(handleChange).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent(/please enter a valid date/i);
      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent('—');
    });

    it('entering invalid calendar date suppresses onChange and displays validation error', () => {
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-early" onChange={handleChange} />);

      const dateInput = screen.getByLabelText(/shift date/i);
      fireEvent.change(dateInput, { target: { value: '2026-02-31' } });

      expect(handleChange).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent(/please enter a valid date/i);
    });
  });

  describe('Quick Actions: Today and Step Navigation', () => {
    it('clicking Today button updates date to today and invokes onChange', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2025-01-01-late" onChange={handleChange} />);

      const todayButton = screen.getByRole('button', { name: /today/i });
      await user.click(todayButton);

      expect(handleChange).toHaveBeenCalledTimes(1);
      expect(handleChange).toHaveBeenCalledWith(`${today}-late`);
      expect(screen.getByLabelText(/shift date/i)).toHaveValue(today);
      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent(`${today}-late`);
    });

    it('clicking Previous Day (<) button decrements date by 1 day and invokes onChange', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-early" onChange={handleChange} />);

      const prevBtn = screen.getByRole('button', { name: /previous day/i });
      await user.click(prevBtn);

      expect(handleChange).toHaveBeenCalledTimes(1);
      expect(handleChange).toHaveBeenCalledWith('2026-11-13-early');
      expect(screen.getByLabelText(/shift date/i)).toHaveValue('2026-11-13');
    });

    it('clicking Next Day (>) button increments date by 1 day and invokes onChange', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-early" onChange={handleChange} />);

      const nextBtn = screen.getByRole('button', { name: /next day/i });
      await user.click(nextBtn);

      expect(handleChange).toHaveBeenCalledTimes(1);
      expect(handleChange).toHaveBeenCalledWith('2026-11-15-early');
      expect(screen.getByLabelText(/shift date/i)).toHaveValue('2026-11-15');
    });

    it('rolls over month and year boundary correctly on Next Day button', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-12-31-night" onChange={handleChange} />);

      const nextBtn = screen.getByRole('button', { name: /next day/i });
      await user.click(nextBtn);

      expect(handleChange).toHaveBeenCalledWith('2027-01-01-night');
      expect(screen.getByLabelText(/shift date/i)).toHaveValue('2027-01-01');
    });

    it('rolls over year boundary correctly on Previous Day button', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2027-01-01-night" onChange={handleChange} />);

      const prevBtn = screen.getByRole('button', { name: /previous day/i });
      await user.click(prevBtn);

      expect(handleChange).toHaveBeenCalledWith('2026-12-31-night');
      expect(screen.getByLabelText(/shift date/i)).toHaveValue('2026-12-31');
    });
  });

  describe('Invalid Prop Handling and Error Recovery', () => {
    it('handles invalid prop string without crashing and renders inline error badge', () => {
      const handleChange = vi.fn();
      render(<ShiftSelector value="invalid-shift" onChange={handleChange} />);

      const errorBadge = screen.getByRole('alert');
      expect(errorBadge).toBeInTheDocument();
      expect(errorBadge).toHaveTextContent('Invalid shift identifier');
      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent('—');
    });

    it('handles invalid Gregorian date in prop without crashing and renders inline error badge', () => {
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-02-31-early" onChange={handleChange} />);

      const errorBadge = screen.getByRole('alert');
      expect(errorBadge).toBeInTheDocument();
      expect(errorBadge).toHaveTextContent('Invalid shift identifier');
    });

    it('clears invalid prop error once user picks a valid date and shift via Today button', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="invalid" onChange={handleChange} />);

      expect(screen.getByText('Invalid shift identifier')).toBeInTheDocument();

      const todayBtn = screen.getByRole('button', { name: /today/i });
      await user.click(todayBtn);

      expect(handleChange).toHaveBeenCalledWith(`${today}-early`);
      expect(screen.queryByText('Invalid shift identifier')).not.toBeInTheDocument();
      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent(`${today}-early`);
    });

    it('clears invalid prop error once user manually enters a valid date', () => {
      const handleChange = vi.fn();
      render(<ShiftSelector value="invalid" onChange={handleChange} />);

      expect(screen.getByText('Invalid shift identifier')).toBeInTheDocument();

      const dateInput = screen.getByLabelText(/shift date/i);
      fireEvent.change(dateInput, { target: { value: '2026-11-14' } });

      expect(handleChange).toHaveBeenCalledWith('2026-11-14-early');
      expect(screen.queryByText('Invalid shift identifier')).not.toBeInTheDocument();
      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent('2026-11-14-early');
    });
  });

  describe('Disabled State', () => {
    it('disables all interactive elements when disabled prop is true', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-early" disabled={true} onChange={handleChange} />);

      const dateInput = screen.getByLabelText(/shift date/i);
      expect(dateInput).toBeDisabled();

      const earlyBtn = screen.getByRole('radio', { name: /early shift/i });
      const lateBtn = screen.getByRole('radio', { name: /late shift/i });
      const nightBtn = screen.getByRole('radio', { name: /night shift/i });
      expect(earlyBtn).toBeDisabled();
      expect(lateBtn).toBeDisabled();
      expect(nightBtn).toBeDisabled();

      const todayBtn = screen.getByRole('button', { name: /today/i });
      const prevBtn = screen.getByRole('button', { name: /previous day/i });
      const nextBtn = screen.getByRole('button', { name: /next day/i });
      expect(todayBtn).toBeDisabled();
      expect(prevBtn).toBeDisabled();
      expect(nextBtn).toBeDisabled();

      // Interactions do not fire callbacks
      await user.click(lateBtn);
      await user.click(todayBtn);
      await user.click(prevBtn);
      expect(handleChange).not.toHaveBeenCalled();
    });
  });

  describe('Accessibility & Keyboard Navigation', () => {
    it('provides accessible radiogroup and radio attributes for shift types', () => {
      render(<ShiftSelector value="2026-11-14-late" onChange={vi.fn()} />);

      const radiogroup = screen.getByRole('radiogroup', { name: /shift type/i });
      expect(radiogroup).toBeInTheDocument();

      const radios = screen.getAllByRole('radio');
      expect(radios).toHaveLength(3);

      expect(screen.getByRole('radio', { name: /early shift/i })).toHaveAttribute('aria-checked', 'false');
      expect(screen.getByRole('radio', { name: /late shift/i })).toHaveAttribute('aria-checked', 'true');
      expect(screen.getByRole('radio', { name: /night shift/i })).toHaveAttribute('aria-checked', 'false');
    });

    it('supports keyboard navigation and activation via Tab and Space/Enter keys', async () => {
      const user = userEvent.setup();
      const handleChange = vi.fn();
      render(<ShiftSelector value="2026-11-14-early" onChange={handleChange} />);

      const nightRadio = screen.getByRole('radio', { name: /night shift/i });
      nightRadio.focus();
      expect(nightRadio).toHaveFocus();

      await user.keyboard(' ');
      expect(handleChange).toHaveBeenCalledWith('2026-11-14-night');

      const nextDayBtn = screen.getByRole('button', { name: /next day/i });
      nextDayBtn.focus();
      expect(nextDayBtn).toHaveFocus();

      await user.keyboard('{Enter}');
      expect(handleChange).toHaveBeenCalledWith('2026-11-15-night');
    });
  });

  describe('External value prop synchronization', () => {
    it('updates internal state when value prop changes externally', () => {
      const handleChange = vi.fn();
      const { rerender } = render(<ShiftSelector value="2026-11-14-early" onChange={handleChange} />);

      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent('2026-11-14-early');

      rerender(<ShiftSelector value="2026-12-25-night" onChange={handleChange} />);

      expect(screen.getByLabelText(/shift date/i)).toHaveValue('2026-12-25');
      expect(screen.getByRole('radio', { name: /night shift/i })).toHaveAttribute('aria-checked', 'true');
      expect(screen.getByTestId('shift-key-badge')).toHaveTextContent('2026-12-25-night');
    });
  });
});
