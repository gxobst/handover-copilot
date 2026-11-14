import React, { useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react';
import {
  type ShiftType,
  SHIFT_TYPES,
  isValidShiftKey,
  parseShiftKey,
  formatShiftKey,
  isValidDateString,
  getLocalDateString,
  stepCalendarDate,
} from '../utils/shiftKey';

export interface ShiftSelectorProps {
  value?: string;
  onChange: (shiftKey: string) => void;
  disabled?: boolean;
  className?: string;
}

const SHIFT_OPTIONS: { type: ShiftType; label: string }[] = [
  { type: 'early', label: 'Early' },
  { type: 'late', label: 'Late' },
  { type: 'night', label: 'Night' },
];

export const ShiftSelector: React.FC<ShiftSelectorProps> = ({
  value,
  onChange,
  disabled = false,
  className = '',
}) => {
  const [prevValue, setPrevValue] = useState<string | undefined>(value);

  const [internalDate, setInternalDate] = useState<string>(() => {
    if (value !== undefined) {
      const parsed = parseShiftKey(value);
      return parsed ? parsed.date : '';
    }
    return getLocalDateString();
  });

  const [internalShiftType, setInternalShiftType] = useState<ShiftType>(() => {
    if (value !== undefined) {
      const parsed = parseShiftKey(value);
      return parsed ? parsed.shiftType : 'early';
    }
    return 'early';
  });

  const [propError, setPropError] = useState<string | null>(() => {
    if (value !== undefined && !isValidShiftKey(value)) {
      return 'Invalid shift identifier';
    }
    return null;
  });

  const [dateError, setDateError] = useState<string | null>(null);

  // Synchronize when the external `value` prop changes during render
  if (value !== prevValue) {
    setPrevValue(value);
    if (value !== undefined) {
      const parsed = parseShiftKey(value);
      if (parsed) {
        setInternalDate(parsed.date);
        setInternalShiftType(parsed.shiftType);
        setPropError(null);
        setDateError(null);
      } else {
        setPropError('Invalid shift identifier');
      }
    }
  }

  const handleShiftTypeSelect = (selectedType: ShiftType) => {
    if (disabled || selectedType === internalShiftType) {
      return;
    }

    setInternalShiftType(selectedType);

    if (isValidDateString(internalDate)) {
      setPropError(null);
      setDateError(null);
      const newShiftKey = formatShiftKey(internalDate, selectedType);
      onChange(newShiftKey);
    } else {
      setDateError('Please enter a valid date');
    }
  };

  const handleDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (disabled) return;
    const newDate = e.target.value;
    setInternalDate(newDate);

    if (!newDate || !isValidDateString(newDate)) {
      setDateError('Please enter a valid date');
      return;
    }

    setDateError(null);
    setPropError(null);
    const newShiftKey = formatShiftKey(newDate, internalShiftType);
    onChange(newShiftKey);
  };

  const handleTodayClick = () => {
    if (disabled) return;
    const today = getLocalDateString();
    setInternalDate(today);
    setDateError(null);
    setPropError(null);
    const newShiftKey = formatShiftKey(today, internalShiftType);
    onChange(newShiftKey);
  };

  const handleStepDay = (deltaDays: number) => {
    if (disabled || !isValidDateString(internalDate)) return;
    const newDate = stepCalendarDate(internalDate, deltaDays);
    if (!newDate) return;

    setInternalDate(newDate);
    setDateError(null);
    setPropError(null);
    const newShiftKey = formatShiftKey(newDate, internalShiftType);
    onChange(newShiftKey);
  };

  const isCurrentKeyValid =
    !propError && !dateError && isValidDateString(internalDate) && SHIFT_TYPES.includes(internalShiftType);

  const activeShiftKey = isCurrentKeyValid
    ? formatShiftKey(internalDate, internalShiftType)
    : null;

  return (
    <div
      className={`flex flex-wrap items-center gap-4 p-3 bg-white border border-slate-300 rounded-lg shadow-sm text-slate-800 ${className}`}
    >
      {/* Date Input with Label and Step Controls */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor="shift-date-input"
          className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-1.5"
        >
          <Calendar className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
          Shift Date
        </label>
        <div className="flex items-center gap-1">
          <input
            id="shift-date-input"
            type="date"
            disabled={disabled}
            value={internalDate}
            onChange={handleDateChange}
            aria-invalid={Boolean(dateError || propError)}
            className={`px-2.5 py-1 text-sm font-medium border rounded-md shadow-sm bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 ${
              dateError || propError ? 'border-red-400 bg-red-50/30' : 'border-slate-300'
            } ${disabled ? 'opacity-50 cursor-not-allowed bg-slate-100' : ''}`}
          />
          <button
            type="button"
            aria-label="Previous Day"
            title="Previous Day"
            disabled={disabled || !isValidDateString(internalDate)}
            onClick={() => handleStepDay(-1)}
            className={`inline-flex items-center justify-center px-2 py-1 text-xs font-bold rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-900 shadow-sm ${
              disabled || !isValidDateString(internalDate)
                ? 'opacity-50 cursor-not-allowed'
                : 'cursor-pointer'
            }`}
          >
            <ChevronLeft className="w-4 h-4 mr-0.5 inline" aria-hidden="true" />
            <span aria-hidden="true">&lt;</span>
          </button>
          <button
            type="button"
            aria-label="Next Day"
            title="Next Day"
            disabled={disabled || !isValidDateString(internalDate)}
            onClick={() => handleStepDay(1)}
            className={`inline-flex items-center justify-center px-2 py-1 text-xs font-bold rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-900 shadow-sm ${
              disabled || !isValidDateString(internalDate)
                ? 'opacity-50 cursor-not-allowed'
                : 'cursor-pointer'
            }`}
          >
            <span aria-hidden="true">&gt;</span>
            <ChevronRight className="w-4 h-4 ml-0.5 inline" aria-hidden="true" />
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={handleTodayClick}
            className={`px-2.5 py-1 text-xs font-semibold rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-900 shadow-sm ${
              disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
            }`}
          >
            Today
          </button>
        </div>
      </div>

      {/* Segmented Shift Type Control */}
      <div className="flex flex-col gap-1">
        <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
          Shift Type
        </span>
        <div
          role="radiogroup"
          aria-label="Shift Type"
          className="inline-flex rounded-md border border-slate-300 p-0.5 bg-slate-100 shadow-sm"
        >
          {SHIFT_OPTIONS.map((option) => {
            const isActive = internalShiftType === option.type;
            return (
              <button
                key={option.type}
                type="button"
                role="radio"
                aria-checked={isActive}
                aria-label={`${option.label} Shift`}
                disabled={disabled}
                onClick={() => handleShiftTypeSelect(option.type)}
                className={`px-3 py-1.5 text-xs font-semibold rounded transition-colors focus:outline-none focus:ring-2 focus:ring-slate-900 ${
                  isActive
                    ? 'bg-slate-900 text-white shadow-sm'
                    : 'bg-white text-slate-700 hover:bg-slate-50 border border-slate-200'
                } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Monospace Badge & Validation Alerts */}
      <div className="flex flex-col gap-1 sm:ml-auto">
        <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          Active Shift
        </span>
        <div className="flex items-center gap-2">
          <span
            data-testid="shift-key-badge"
            className="font-mono text-xs font-semibold px-2.5 py-1 rounded bg-slate-100 text-slate-900 border border-slate-300 tracking-wide"
          >
            {activeShiftKey ?? '—'}
          </span>
          {propError && (
            <span
              role="alert"
              className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-red-100 text-red-800 border border-red-300"
            >
              {propError}
            </span>
          )}
          {dateError && (
            <span
              role="alert"
              className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800 border border-amber-300"
            >
              {dateError}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
