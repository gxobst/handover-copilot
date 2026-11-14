import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Sparkles,
  RefreshCw,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Database,
  Copy,
  RotateCcw,
  Check,
} from 'lucide-react';
import type { ReportResponse } from '../types/api';
import {
  reportsApi,
  type ApiError,
  toProblemDetails,
  extractTraceId,
  isApiError,
} from '../services';
import { isValidShiftKey } from '../utils/shiftKey';

export interface GenerateButtonProps {
  /** Current active shift identifier in YYYY-MM-DD-(early|late|night) format */
  shiftKey: string;
  /** Number of logged events for the selected shift */
  eventCount: number;
  /** Whether a report has already been generated for this shift */
  hasExistingReport?: boolean;
  /** Optional version number of the current existing report */
  currentVersion?: number;
  /** Callback fired upon successful 201 generation */
  onReportGenerated?: (report: ReportResponse) => void;
  /** Callback fired upon generation failure */
  onError?: (error: Error | ApiError) => void;
  /** Optional prop to disable interaction externally */
  disabled?: boolean;
  /** Optional container CSS class name */
  className?: string;
}

interface ErrorBannerState {
  message: string;
  detail?: string;
  traceId?: string;
}

export const GenerateButton: React.FC<GenerateButtonProps> = ({
  shiftKey,
  eventCount,
  hasExistingReport = false,
  currentVersion,
  onReportGenerated,
  onError,
  disabled = false,
  className = '',
}) => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isColdStarting, setIsColdStarting] = useState(false);
  const [coldStartElapsed, setColdStartElapsed] = useState(0);
  const [errorState, setErrorState] = useState<ErrorBannerState | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [copiedTraceId, setCopiedTraceId] = useState(false);
  const [hasLocallyGenerated, setHasLocallyGenerated] = useState(false);

  const isSubmittingRef = useRef(false);
  const coldStartTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const coldStartIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const successTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Validation
  const isShiftValid = Boolean(shiftKey && isValidShiftKey(shiftKey));
  const hasZeroEvents = eventCount <= 0;
  const isDisabled = disabled || !isShiftValid || hasZeroEvents;

  // Reset shift-specific states when shiftKey changes during render
  const [prevShiftKey, setPrevShiftKey] = useState(shiftKey);
  if (shiftKey !== prevShiftKey) {
    setPrevShiftKey(shiftKey);
    setHasLocallyGenerated(false);
    setErrorState(null);
    setSuccessMessage(null);
  }

  // Determine whether this is a regeneration
  const isRegenerate = Boolean(
    hasExistingReport ||
    (currentVersion !== undefined && currentVersion > 0) ||
    hasLocallyGenerated
  );

  // Clean up all timers on unmount
  useEffect(() => {
    return () => {
      if (coldStartTimeoutRef.current) {
        clearTimeout(coldStartTimeoutRef.current);
      }
      if (coldStartIntervalRef.current) {
        clearInterval(coldStartIntervalRef.current);
      }
      if (successTimeoutRef.current) {
        clearTimeout(successTimeoutRef.current);
      }
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  // Determine helper / warning message and accessibility descriptor
  let warningMessage: string | null = null;
  let helperId: string | undefined = undefined;

  if (!isShiftValid) {
    warningMessage = 'Select a valid shift before generating a report.';
    helperId = 'generate-shift-warning';
  } else if (hasZeroEvents) {
    warningMessage = 'At least 1 shift event is required to generate a handover report.';
    helperId = 'generate-zero-events-helper';
  }

  const clearTimers = useCallback(() => {
    if (coldStartTimeoutRef.current) {
      clearTimeout(coldStartTimeoutRef.current);
      coldStartTimeoutRef.current = null;
    }
    if (coldStartIntervalRef.current) {
      clearInterval(coldStartIntervalRef.current);
      coldStartIntervalRef.current = null;
    }
  }, []);

  const handleGenerate = useCallback(async () => {
    // Guard against duplicate in-flight requests or disabled states
    if (isSubmittingRef.current || isDisabled || isSubmitting) {
      return;
    }

    isSubmittingRef.current = true;
    setIsSubmitting(true);
    setIsColdStarting(false);
    setColdStartElapsed(0);
    setErrorState(null);
    setSuccessMessage(null);

    if (successTimeoutRef.current) {
      clearTimeout(successTimeoutRef.current);
      successTimeoutRef.current = null;
    }

    clearTimers();

    // Trigger cold-start banner when request exceeds 3 seconds
    coldStartTimeoutRef.current = setTimeout(() => {
      setIsColdStarting(true);
      setColdStartElapsed(3);

      coldStartIntervalRef.current = setInterval(() => {
        setColdStartElapsed((prev) => prev + 1);
      }, 1000);
    }, 3000);

    try {
      const report = await reportsApi.generateReport({ shiftKey });

      clearTimers();
      setIsColdStarting(false);
      setHasLocallyGenerated(true);

      const successText = `Handover report v${report.version} generated successfully.`;
      setSuccessMessage(successText);

      successTimeoutRef.current = setTimeout(() => {
        setSuccessMessage(null);
      }, 5000);

      onReportGenerated?.(report);
    } catch (err: unknown) {
      clearTimers();
      setIsColdStarting(false);

      const pd = toProblemDetails(err);
      const traceId = extractTraceId(err) || pd.traceId;

      let message = pd.detail || 'An unexpected error occurred while generating the report.';
      let detail: string | undefined = undefined;

      if (pd.status === 422) {
        message = pd.detail || 'No events found for shift.';
      } else if (pd.status === 502) {
        message = 'Report generation failed: LLM models unavailable. Please try again.';
        if (pd.detail && pd.detail !== message) {
          detail = pd.detail;
        }
      } else if (pd.status === 429) {
        message = 'Rate limit exceeded. Please wait a few moments before trying again.';
        if (pd.detail && pd.detail !== message) {
          detail = pd.detail;
        }
      } else if (
        pd.status === 0 ||
        pd.title === 'Network Error' ||
        (err instanceof TypeError && err.message.toLowerCase().includes('fetch'))
      ) {
        message =
          'Unable to connect to the handover generation service. Check your connection or server status.';
      }

      setErrorState({
        message,
        detail,
        traceId,
      });

      const normalizedError =
        err instanceof Error || isApiError(err)
          ? (err as Error | ApiError)
          : new Error(typeof err === 'string' ? err : 'Report generation failed');

      onError?.(normalizedError);
    } finally {
      setIsSubmitting(false);
      isSubmittingRef.current = false;
    }
  }, [
    isDisabled,
    isSubmitting,
    clearTimers,
    shiftKey,
    onReportGenerated,
    onError,
  ]);

  const handleCopyTraceId = useCallback(async () => {
    if (!errorState?.traceId) return;

    try {
      if (
        typeof navigator !== 'undefined' &&
        navigator.clipboard &&
        typeof navigator.clipboard.writeText === 'function'
      ) {
        await navigator.clipboard.writeText(errorState.traceId);
      }
      setCopiedTraceId(true);
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
      copyTimeoutRef.current = setTimeout(() => {
        setCopiedTraceId(false);
      }, 2000);
    } catch {
      // Graceful degradation when clipboard API is unavailable
    }
  }, [errorState]);

  const accessibleName = isSubmitting
    ? 'Generating Handover...'
    : isRegenerate
    ? 'Regenerate shift handover report'
    : 'Generate shift handover report';

  return (
    <div className={`flex flex-col gap-2 ${className}`.trim()}>
      <div>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={isDisabled || isSubmitting}
          aria-disabled={isDisabled || isSubmitting ? 'true' : undefined}
          aria-busy={isSubmitting ? 'true' : undefined}
          aria-describedby={helperId}
          aria-label={accessibleName}
          className={`inline-flex items-center justify-center px-5 py-2.5 text-sm font-semibold rounded-md shadow-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-900 ${
            isDisabled || isSubmitting
              ? 'bg-slate-200 text-slate-500 cursor-not-allowed border border-slate-300'
              : 'bg-slate-900 text-white hover:bg-slate-800 border border-transparent cursor-pointer'
          }`}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
              <span>Generating Handover...</span>
            </>
          ) : isRegenerate ? (
            <>
              <RefreshCw className="w-4 h-4 mr-2" aria-hidden="true" />
              <span>Regenerate Handover</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4 mr-2" aria-hidden="true" />
              <span>Generate Handover</span>
            </>
          )}
        </button>
      </div>

      {/* Helper / Warning Message for Disabled State */}
      {warningMessage && helperId && (
        <div
          id={helperId}
          role="note"
          className="flex items-center gap-1.5 text-xs text-slate-600"
        >
          <AlertCircle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0" aria-hidden="true" />
          <span>{warningMessage}</span>
        </div>
      )}

      {/* Cold-Start Progress UX */}
      {isColdStarting && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center justify-between gap-3 p-3 text-sm rounded-md bg-amber-50 border border-amber-300 text-amber-900 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-amber-700 flex-shrink-0 animate-pulse" aria-hidden="true" />
            <span>
              Waking up the database — the first request after an idle period may take up to 20 s.
            </span>
          </div>
          <div className="text-xs font-mono font-semibold text-amber-800 whitespace-nowrap">
            Elapsed: {coldStartElapsed}s
          </div>
        </div>
      )}

      {/* Transient Success Banner */}
      {successMessage && !isSubmitting && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 p-3 text-sm font-medium rounded-md bg-emerald-50 border border-emerald-300 text-emerald-900 shadow-sm"
        >
          <CheckCircle2 className="w-4 h-4 text-emerald-700 flex-shrink-0" aria-hidden="true" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* RFC 9457 Problem Details Error Callout Banner */}
      {errorState && !isSubmitting && (
        <div
          role="alert"
          aria-live="assertive"
          className="flex flex-col gap-2 p-4 text-sm rounded-md bg-red-50 border border-red-300 text-red-900 shadow-sm"
        >
          <div className="flex items-start gap-2">
            <AlertCircle className="w-5 h-5 text-red-700 flex-shrink-0 mt-0.5" aria-hidden="true" />
            <div className="flex-1">
              <p className="font-semibold text-red-900">{errorState.message}</p>
              {errorState.detail && (
                <p className="text-xs text-red-700 mt-1">{errorState.detail}</p>
              )}
            </div>
          </div>

          {errorState.traceId && (
            <div className="flex items-center gap-2 pl-7 pt-1">
              <span className="font-mono text-xs font-semibold text-red-800">
                Trace ID: {errorState.traceId}
              </span>
              <button
                type="button"
                onClick={handleCopyTraceId}
                aria-label="Copy Trace ID"
                className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded border border-red-300 bg-white text-red-700 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-red-600 transition-colors cursor-pointer"
              >
                {copiedTraceId ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-600" aria-hidden="true" />
                    <span>Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" aria-hidden="true" />
                    <span>Copy</span>
                  </>
                )}
              </button>
            </div>
          )}

          <div className="pl-7 pt-1">
            <button
              type="button"
              onClick={handleGenerate}
              className="inline-flex items-center px-3 py-1.5 text-xs font-semibold rounded bg-red-700 text-white hover:bg-red-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-red-600 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5 mr-1.5" aria-hidden="true" />
              <span>Try Again</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default GenerateButton;
