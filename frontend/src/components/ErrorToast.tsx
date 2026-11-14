import React, { useState, useEffect, useRef, useCallback } from 'react';
import { AlertCircle, X, Copy, Check } from 'lucide-react';
import type { ToastMessage } from '../context/ToastContext';

export interface ErrorToastProps {
  toast: ToastMessage;
  onDismiss: (id: string) => void;
  className?: string;
}

export const ErrorToast: React.FC<ErrorToastProps> = ({
  toast,
  onDismiss,
  className = '',
}) => {
  const duration = toast.duration ?? 8000;
  const remainingTimeRef = useRef<number>(duration);
  const startTimeRef = useRef<number | null>(null);
  const timerIdRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isHoveredRef = useRef<boolean>(false);
  const isFocusedRef = useRef<boolean>(false);

  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startTimer = useCallback(() => {
    if (duration <= 0 || remainingTimeRef.current <= 0) return;
    if (timerIdRef.current !== null) return;
    if (isHoveredRef.current || isFocusedRef.current) return;

    startTimeRef.current = Date.now();
    timerIdRef.current = setTimeout(() => {
      onDismiss(toast.id);
    }, remainingTimeRef.current);
  }, [duration, onDismiss, toast.id]);

  const pauseTimer = useCallback(() => {
    if (timerIdRef.current !== null) {
      clearTimeout(timerIdRef.current);
      timerIdRef.current = null;
    }
    if (startTimeRef.current !== null) {
      const elapsed = Date.now() - startTimeRef.current;
      remainingTimeRef.current = Math.max(0, remainingTimeRef.current - elapsed);
      startTimeRef.current = null;
    }
  }, []);

  useEffect(() => {
    startTimer();
    return () => {
      if (timerIdRef.current !== null) {
        clearTimeout(timerIdRef.current);
        timerIdRef.current = null;
      }
    };
  }, [startTimer]);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current !== null) {
        clearTimeout(copyTimeoutRef.current);
        copyTimeoutRef.current = null;
      }
    };
  }, []);

  const handleMouseEnter = () => {
    isHoveredRef.current = true;
    pauseTimer();
  };

  const handleMouseLeave = () => {
    isHoveredRef.current = false;
    if (!isFocusedRef.current) {
      startTimer();
    }
  };

  const handleFocus = () => {
    isFocusedRef.current = true;
    pauseTimer();
  };

  const handleBlur = (e: React.FocusEvent<HTMLDivElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
      isFocusedRef.current = false;
      if (!isHoveredRef.current) {
        startTimer();
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onDismiss(toast.id);
    }
  };

  const handleCopyTraceId = async () => {
    if (!toast.traceId) return;

    try {
      if (
        typeof navigator !== 'undefined' &&
        navigator.clipboard &&
        typeof navigator.clipboard.writeText === 'function'
      ) {
        await navigator.clipboard.writeText(toast.traceId);
        setCopyState('copied');
      } else {
        setCopyState('failed');
      }
    } catch {
      setCopyState('failed');
    }

    if (copyTimeoutRef.current !== null) {
      clearTimeout(copyTimeoutRef.current);
    }
    copyTimeoutRef.current = setTimeout(() => {
      setCopyState('idle');
    }, 2000);
  };

  const hasTraceId = Boolean(toast.traceId && toast.traceId.trim().length > 0);
  const hasStatus = typeof toast.status === 'number' && toast.status > 0;

  return (
    <div
      role="alert"
      aria-live="assertive"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onFocus={handleFocus}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      className={`relative flex items-start gap-3 bg-red-50 border-2 border-red-400 text-red-950 rounded-lg shadow-lg p-4 pointer-events-auto transition-all ${className}`.trim()}
    >
      <AlertCircle
        className="text-red-600 flex-shrink-0 w-5 h-5 mt-0.5"
        aria-hidden="true"
      />

      <div className="flex-1 min-w-0 pr-6">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-bold text-sm text-red-900 leading-tight">
            {toast.title}
          </h3>
          {hasStatus && (
            <span
              data-testid="status-badge"
              className="bg-red-100 text-red-800 text-xs font-mono font-semibold px-2 py-0.5 rounded border border-red-200"
            >
              {toast.status}
            </span>
          )}
        </div>

        <div className="text-xs text-red-800 break-words mt-1 max-h-36 overflow-y-auto">
          {toast.detail}
        </div>

        {hasTraceId && (
          <div className="mt-2 pt-2 border-t border-red-200/80 flex items-center justify-between gap-2 text-xs">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-red-900 font-semibold flex-shrink-0">
                Trace ID:
              </span>
              <span
                data-testid="trace-id-value"
                className="font-mono text-xs bg-red-100/70 text-red-900 px-2 py-0.5 rounded border border-red-200 select-all truncate"
                title={toast.traceId}
              >
                {toast.traceId}
              </span>
            </div>

            <button
              type="button"
              onClick={handleCopyTraceId}
              aria-label={
                copyState === 'copied'
                  ? 'Copied!'
                  : copyState === 'failed'
                  ? 'Copy failed'
                  : 'Copy Trace ID'
              }
              title={
                copyState === 'copied'
                  ? 'Copied!'
                  : copyState === 'failed'
                  ? 'Copy failed'
                  : 'Copy Trace ID'
              }
              className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs font-medium text-red-800 hover:text-red-950 hover:bg-red-200/60 rounded focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none transition-colors flex-shrink-0"
            >
              {copyState === 'copied' ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-700" aria-hidden="true" />
                  <span className="text-[11px] text-emerald-800 font-semibold">
                    Copied!
                  </span>
                </>
              ) : copyState === 'failed' ? (
                <>
                  <AlertCircle className="w-3.5 h-3.5 text-red-700" aria-hidden="true" />
                  <span className="text-[11px] text-red-800 font-semibold">
                    Copy failed
                  </span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-red-700" aria-hidden="true" />
                  <span className="sr-only">Copy Trace ID</span>
                </>
              )}
            </button>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss error notification"
        className="absolute top-3 right-3 text-red-700 hover:text-red-950 p-1 rounded hover:bg-red-200/60 transition-colors focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none flex-shrink-0"
      >
        <X className="w-4 h-4" aria-hidden="true" />
      </button>
    </div>
  );
};

export default ErrorToast;
