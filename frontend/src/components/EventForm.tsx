import React, { useState, useRef, useEffect } from 'react';
import { Loader2, Plus, AlertCircle, CheckCircle2, Clock } from 'lucide-react';
import type { Category, EventResponse, EventCreateRequest } from '../types';
import { eventsApi, type ApiError, toProblemDetails, extractTraceId } from '../services';
import { isValidShiftKey } from '../utils/shiftKey';

export interface EventFormProps {
  /**
   * The active shift identifier (e.g. "2026-11-14-early").
   */
  shiftKey: string;
  /**
   * Optional callback fired when an event is successfully created.
   */
  onEventCreated?: (event: EventResponse) => void;
  /**
   * Optional callback fired when an event creation request fails.
   */
  onError?: (error: Error | ApiError) => void;
  /**
   * Disables all inputs, buttons, and submissions in the form.
   */
  disabled?: boolean;
  /**
   * Optional additional CSS classes applied to the root form container.
   */
  className?: string;
}

interface CategoryOption {
  value: Category;
  label: string;
  badgeClasses: string;
}

const CATEGORY_OPTIONS: readonly CategoryOption[] = [
  {
    value: 'downtime',
    label: 'Downtime',
    badgeClasses: 'bg-amber-100 text-amber-800 border-amber-300',
  },
  {
    value: 'quality',
    label: 'Quality',
    badgeClasses: 'bg-purple-100 text-purple-800 border-purple-300',
  },
  {
    value: 'safety',
    label: 'Safety',
    badgeClasses: 'bg-red-100 text-red-800 border-red-300 font-semibold',
  },
  {
    value: 'info',
    label: 'Info',
    badgeClasses: 'bg-slate-100 text-slate-800 border-slate-300',
  },
];

interface FormApiErrorState {
  detail: string;
  traceId?: string;
}

export const EventForm: React.FC<EventFormProps> = ({
  shiftKey,
  onEventCreated,
  onError,
  disabled = false,
  className = '',
}) => {
  const [machine, setMachine] = useState('');
  const [category, setCategory] = useState<Category>('downtime');
  const [note, setNote] = useState('');

  const [machineError, setMachineError] = useState<string | null>(null);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<FormApiErrorState | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isColdStarting, setIsColdStarting] = useState(false);

  const isSubmittingRef = useRef(false);
  const coldStartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Validate shiftKey
  const isShiftValid = Boolean(shiftKey && isValidShiftKey(shiftKey));

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current);
      }
      if (successTimerRef.current) {
        clearTimeout(successTimerRef.current);
      }
    };
  }, []);

  const handleMachineChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setMachine(e.target.value);
    if (machineError) {
      setMachineError(null);
    }
    if (successMessage) {
      setSuccessMessage(null);
    }
  };

  const handleCategorySelect = (selectedCategory: Category) => {
    if (disabled || isSubmitting) return;
    setCategory(selectedCategory);
    if (successMessage) {
      setSuccessMessage(null);
    }
  };

  const handleNoteChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    if (value.length <= 2000) {
      setNote(value);
    }
    if (noteError) {
      setNoteError(null);
    }
    if (successMessage) {
      setSuccessMessage(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Prevent double submission, disabled form, or submission with invalid shiftKey
    if (isSubmittingRef.current || isSubmitting || disabled || !isShiftValid) {
      return;
    }

    let hasValidationError = false;
    const trimmedMachine = machine.trim();
    const trimmedNote = note.trim();

    if (!trimmedMachine) {
      setMachineError('Machine name is required');
      hasValidationError = true;
    } else {
      setMachineError(null);
    }

    if (!trimmedNote) {
      setNoteError('Note is required');
      hasValidationError = true;
    } else {
      setNoteError(null);
    }

    if (hasValidationError) {
      return;
    }

    // Set in-flight submission state
    isSubmittingRef.current = true;
    setIsSubmitting(true);
    setApiError(null);
    setSuccessMessage(null);
    setIsColdStarting(false);

    // Start 3-second cold-start timer
    coldStartTimerRef.current = setTimeout(() => {
      setIsColdStarting(true);
    }, 3000);

    const payload: EventCreateRequest = {
      shiftKey,
      machine: trimmedMachine,
      category,
      note: trimmedNote,
    };

    try {
      const response = await eventsApi.createEvent(payload);

      // Reset form fields on success
      setMachine('');
      setNote('');
      setCategory('downtime');
      setMachineError(null);
      setNoteError(null);
      setApiError(null);
      setSuccessMessage('Event logged successfully');

      if (successTimerRef.current) {
        clearTimeout(successTimerRef.current);
      }
      successTimerRef.current = setTimeout(() => {
        setSuccessMessage(null);
      }, 5000);

      if (onEventCreated) {
        onEventCreated(response);
      }
    } catch (err: unknown) {
      const pd = toProblemDetails(err);
      const traceId = extractTraceId(err) ?? pd.traceId;
      const detail =
        pd.detail || (err instanceof Error ? err.message : 'Failed to record event');

      setApiError({
        detail,
        traceId,
      });

      if (onError) {
        onError(err as Error | ApiError);
      }
    } finally {
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current);
        coldStartTimerRef.current = null;
      }
      setIsColdStarting(false);
      setIsSubmitting(false);
      isSubmittingRef.current = false;
    }
  };

  const isFormControlsDisabled = disabled || isSubmitting;

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className={`flex flex-col gap-4 p-4 bg-white border border-slate-300 rounded-lg shadow-sm text-slate-800 ${className}`}
    >
      {/* Invalid Shift Warning Banner */}
      {!isShiftValid && (
        <div
          role="alert"
          aria-live="polite"
          className="flex items-center gap-2 p-3 text-sm font-medium rounded-md bg-amber-50 border border-amber-300 text-amber-900"
        >
          <AlertCircle className="w-4 h-4 text-amber-700 flex-shrink-0" aria-hidden="true" />
          <span>A valid shift must be selected before logging events</span>
        </div>
      )}

      {/* Machine / Station Input */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor="machine"
          className="text-xs font-bold text-slate-700 uppercase tracking-wider"
        >
          Machine / Station
        </label>
        <input
          id="machine"
          name="machine"
          type="text"
          placeholder="e.g. Press-01, Conveyor-B"
          disabled={isFormControlsDisabled}
          value={machine}
          onChange={handleMachineChange}
          aria-invalid={Boolean(machineError)}
          aria-describedby={machineError ? 'machine-error' : undefined}
          className={`px-3 py-2 text-sm border rounded-md shadow-sm bg-white text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900 ${
            machineError ? 'border-red-500 bg-red-50/20' : 'border-slate-300'
          } ${isFormControlsDisabled ? 'opacity-50 cursor-not-allowed bg-slate-100' : ''}`}
        />
        {machineError && (
          <span
            id="machine-error"
            role="alert"
            className="text-xs font-medium text-red-600 flex items-center gap-1 mt-0.5"
          >
            <AlertCircle className="w-3.5 h-3.5 inline flex-shrink-0" aria-hidden="true" />
            {machineError}
          </span>
        )}
      </div>

      {/* Category Selector */}
      <div className="flex flex-col gap-1.5">
        <span
          id="category-label"
          className="text-xs font-bold text-slate-700 uppercase tracking-wider"
        >
          Category
        </span>
        <div
          role="radiogroup"
          aria-labelledby="category-label"
          className="grid grid-cols-2 sm:grid-cols-4 gap-2"
        >
          {CATEGORY_OPTIONS.map((opt) => {
            const isSelected = category === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={isSelected}
                aria-label={opt.label}
                disabled={isFormControlsDisabled}
                onClick={() => handleCategorySelect(opt.value)}
                className={`px-3 py-2 text-xs rounded-md border text-center transition-all focus:outline-none focus:ring-2 focus:ring-slate-900 ${
                  opt.badgeClasses
                } ${
                  isSelected
                    ? 'ring-2 ring-offset-1 ring-slate-800 font-bold shadow-sm'
                    : 'opacity-70 hover:opacity-100'
                } ${isFormControlsDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Note Textarea & Dynamic Character Counter */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor="note"
          className="text-xs font-bold text-slate-700 uppercase tracking-wider"
        >
          Event Note
        </label>
        <textarea
          id="note"
          name="note"
          rows={4}
          maxLength={2000}
          placeholder="Describe the incident, stoppage reason, or observation..."
          disabled={isFormControlsDisabled}
          value={note}
          onChange={handleNoteChange}
          aria-invalid={Boolean(noteError)}
          aria-describedby={noteError ? 'note-error' : 'char-counter'}
          className={`px-3 py-2 text-sm border rounded-md shadow-sm bg-white text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900 resize-y min-h-[90px] ${
            noteError ? 'border-red-500 bg-red-50/20' : 'border-slate-300'
          } ${isFormControlsDisabled ? 'opacity-50 cursor-not-allowed bg-slate-100' : ''}`}
        />
        <div className="flex items-center justify-between text-xs mt-0.5">
          <div>
            {noteError && (
              <span
                id="note-error"
                role="alert"
                className="font-medium text-red-600 flex items-center gap-1"
              >
                <AlertCircle className="w-3.5 h-3.5 inline flex-shrink-0" aria-hidden="true" />
                {noteError}
              </span>
            )}
          </div>
          <span
            id="char-counter"
            data-testid="char-counter"
            aria-live="polite"
            className={`font-mono text-xs ml-auto ${
              note.length >= 2000
                ? 'text-red-600 font-bold'
                : note.length > 1900
                ? 'text-amber-600 font-medium'
                : 'text-slate-500'
            }`}
          >
            {note.length} / 2000
          </span>
        </div>
      </div>

      {/* Cold-start Alert (>3s In-Flight) */}
      {isColdStarting && (
        <div
          role="alert"
          aria-live="polite"
          className="flex items-center gap-2 p-3 text-sm rounded-md bg-amber-50 border border-amber-300 text-amber-900"
        >
          <Clock className="w-4 h-4 text-amber-700 flex-shrink-0 animate-pulse" aria-hidden="true" />
          <span>
            Waking up the database — the first request after an idle period may take up to 20 s.
          </span>
        </div>
      )}

      {/* Inline RFC 9457 API Error Alert */}
      {apiError && (
        <div
          role="alert"
          aria-live="polite"
          className="flex flex-col gap-1 p-3 text-sm rounded-md bg-red-50 border border-red-300 text-red-900"
        >
          <div className="flex items-center gap-2 font-medium">
            <AlertCircle className="w-4 h-4 text-red-700 flex-shrink-0" aria-hidden="true" />
            <span>{apiError.detail}</span>
          </div>
          {apiError.traceId && (
            <div className="text-xs text-red-700 font-mono pl-6">
              Trace ID: {apiError.traceId}
            </div>
          )}
        </div>
      )}

      {/* Transient Success Banner */}
      {successMessage && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 p-3 text-sm font-medium rounded-md bg-emerald-50 border border-emerald-300 text-emerald-900"
        >
          <CheckCircle2 className="w-4 h-4 text-emerald-700 flex-shrink-0" aria-hidden="true" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Submit Action */}
      <div className="flex justify-end pt-2">
        <button
          type="submit"
          disabled={disabled || isSubmitting || !isShiftValid}
          className={`inline-flex items-center justify-center px-4 py-2 text-sm font-semibold rounded-md shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-slate-900 ${
            disabled || isSubmitting || !isShiftValid
              ? 'bg-slate-300 text-slate-500 cursor-not-allowed border border-slate-300'
              : 'bg-slate-900 text-white hover:bg-slate-800 border border-transparent cursor-pointer'
          }`}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 mr-1.5 animate-spin" aria-hidden="true" />
              <span>Logging...</span>
            </>
          ) : (
            <>
              <Plus className="w-4 h-4 mr-1.5" aria-hidden="true" />
              <span>Log Event</span>
            </>
          )}
        </button>
      </div>
    </form>
  );
};

export default EventForm;
