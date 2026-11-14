/* eslint-disable react-refresh/only-export-components */
import React, { createContext, useContext, useState, useCallback } from 'react';
import {
  type ApiError,
  toProblemDetails,
  extractTraceId,
} from '../services/errors';

export interface ToastMessage {
  id: string;
  createdAt: number;
  title: string;
  detail: string;
  status?: number;
  traceId?: string;
  type?: string;
  duration?: number;
}

export interface ToastOptions {
  duration?: number;
  title?: string;
  detail?: string;
  status?: number;
  traceId?: string;
  type?: string;
}

export interface ToastContextValue {
  showError: (error: unknown, options?: ToastOptions) => string;
  showToast: (toast: Omit<ToastMessage, 'id' | 'createdAt'>) => string;
  dismissToast: (id: string) => void;
  clearToasts: () => void;
  toasts: ToastMessage[];
}

export const ToastContext = createContext<ToastContextValue | undefined>(undefined);

const MAX_TOASTS = 5;
const DEFAULT_DURATION = 8000;

function generateToastId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `toast-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

function sanitizeDetail(detail: string): string {
  if (!detail) return '';
  // Sanitize raw HTML tags if upstream gateway responded with html
  const sanitized = detail.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  return sanitized || detail;
}

function normalizeError(error: unknown, options?: ToastOptions): {
  title: string;
  detail: string;
  status?: number;
  traceId?: string;
  type?: string;
} {
  // Case 1: Null, undefined, or empty string error
  if (error === null || error === undefined || (typeof error === 'string' && error.trim().length === 0)) {
    return {
      title: options?.title ?? 'Unknown Error',
      detail: sanitizeDetail(options?.detail ?? 'An unexpected error occurred.'),
      status: options?.status,
      traceId: options?.traceId,
      type: options?.type ?? 'about:blank',
    };
  }

  // Case 2: Plain string error
  if (typeof error === 'string') {
    return {
      title: options?.title ?? 'Error',
      detail: sanitizeDetail(options?.detail ?? error.trim()),
      status: options?.status,
      traceId: options?.traceId,
      type: options?.type ?? 'about:blank',
    };
  }

  // Case 3: Error object
  let title = options?.title;
  let detail = options?.detail;
  let status = options?.status;
  let traceId = options?.traceId;
  let type = options?.type;

  // Extract trace ID from error if not explicitly in options
  if (!traceId) {
    traceId = extractTraceId(error);
  }

  const isNativeError = error instanceof Error;
  const isCustomApiError =
    typeof error === 'object' &&
    error !== null &&
    ('problemDetails' in error || (error as ApiError).name === 'ApiError');

  if (isNativeError && !isCustomApiError) {
    const nativeErr = error as Error;
    // Network disconnect / TypeError fetch check
    if (
      nativeErr.name === 'TypeError' &&
      nativeErr.message.toLowerCase().includes('fetch')
    ) {
      title = title ?? 'Network Error';
      detail = detail ?? 'Unable to connect to the server. Please check your network connection.';
      status = status ?? 0;
      type = type ?? 'about:blank';
    } else {
      const defaultTitle =
        nativeErr.name && nativeErr.name !== 'Error'
          ? nativeErr.name
          : 'Application Error';
      title = title ?? defaultTitle;
      detail = detail ?? (nativeErr.message || 'An unexpected error occurred.');
      status = status ?? (error as { status?: number }).status;
      type = type ?? 'about:blank';
    }
  } else if (typeof error === 'object' && error !== null) {
    const errObj = error as Record<string, unknown>;

    // First check direct properties on the object
    if (typeof errObj.title === 'string' && errObj.title.trim()) {
      title = title ?? errObj.title.trim();
    }
    if (typeof errObj.detail === 'string' && errObj.detail.trim()) {
      detail = detail ?? errObj.detail.trim();
    }
    if (typeof errObj.status === 'number') {
      status = status ?? errObj.status;
    }
    if (typeof errObj.type === 'string') {
      type = type ?? errObj.type;
    }

    // Next check toProblemDetails fallback
    const pd = toProblemDetails(error);
    title = title ?? pd.title;
    detail = detail ?? pd.detail;
    status = status ?? pd.status;
    type = type ?? pd.type;
    if (!traceId) {
      traceId = pd.traceId ?? (pd['trace_id'] as string | undefined);
    }
  }

  // Handle status: 0 specifically for network disconnect / CORS
  if (status === 0 && (!title || title === 'Error')) {
    title = 'Network Error';
    detail = detail ?? 'Unable to connect to the server. Please check your network connection.';
  }

  return {
    title: title || 'Error',
    detail: sanitizeDetail(detail || 'An unexpected error occurred.'),
    status,
    traceId: traceId ? String(traceId).trim() : undefined,
    type: type || 'about:blank',
  };
}

export const ToastProvider: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const clearToasts = useCallback(() => {
    setToasts([]);
  }, []);

  const showToast = useCallback((toast: Omit<ToastMessage, 'id' | 'createdAt'>) => {
    const id = generateToastId();
    const createdAt = Date.now();
    const newToast: ToastMessage = {
      ...toast,
      id,
      createdAt,
      duration: toast.duration ?? DEFAULT_DURATION,
    };

    setToasts((prev) => {
      const next = [...prev, newToast];
      if (next.length > MAX_TOASTS) {
        return next.slice(next.length - MAX_TOASTS);
      }
      return next;
    });

    return id;
  }, []);

  const showError = useCallback(
    (error: unknown, options?: ToastOptions) => {
      const normalized = normalizeError(error, options);
      return showToast({
        ...normalized,
        duration: options?.duration ?? DEFAULT_DURATION,
      });
    },
    [showToast]
  );

  return (
    <ToastContext.Provider
      value={{
        showError,
        showToast,
        dismissToast,
        clearToasts,
        toasts,
      }}
    >
      {children}
    </ToastContext.Provider>
  );
};

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}
