import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Settings,
  ShieldAlert,
  Lock,
  Key,
  Eye,
  EyeOff,
  Save,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  Cpu,
  Zap,
  ShieldCheck,
  Copy,
  Check,
  Clock,
} from 'lucide-react';
import type { AdminSettingsResponse, AdminSettingsUpdate } from '../types/api.ts';
import {
  adminApi,
  toProblemDetails,
  extractTraceId,
} from '../services';

const MODEL_NAME_REGEX = /^[a-zA-Z0-9._/-]+$/;
const MAX_MODEL_NAME_LENGTH = 128;

function validateModelName(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return 'Model name is required.';
  }
  if (trimmed.length > MAX_MODEL_NAME_LENGTH) {
    return `Model name cannot exceed ${MAX_MODEL_NAME_LENGTH} characters.`;
  }
  if (!MODEL_NAME_REGEX.test(trimmed)) {
    return "Model name contains invalid characters. Only alphanumeric, '.', '_', '/', and '-' are allowed.";
  }
  return null;
}

export interface AdminPanelTriggerProps {
  onClick?: () => void;
  className?: string;
  disabled?: boolean;
  label?: string;
}

export const AdminPanelTrigger: React.FC<AdminPanelTriggerProps> = ({
  onClick,
  className = '',
  disabled = false,
  label = 'Admin Settings',
}) => {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={`inline-flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700 hover:text-white focus:outline-none focus:ring-2 focus:ring-slate-400 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
    >
      <Settings className="w-4 h-4 text-slate-300" aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
};

export interface AdminPanelProps {
  isOpen?: boolean;
  onClose?: () => void;
  initialToken?: string;
  className?: string;
}

interface ErrorBannerState {
  title: string;
  detail: string;
  traceId?: string;
  status?: number;
  isAuthError?: boolean;
}

export const AdminPanel: React.FC<AdminPanelProps> = ({
  isOpen = true,
  onClose,
  initialToken,
  className = '',
}) => {
  const [token, setToken] = useState<string>(initialToken?.trim() || '');
  const [tokenInput, setTokenInput] = useState<string>(initialToken?.trim() || '');
  const [showToken, setShowToken] = useState<boolean>(false);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);

  const [settings, setSettings] = useState<AdminSettingsResponse | null>(null);
  const [activeModelInput, setActiveModelInput] = useState<string>('');
  const [fallbackModelInput, setFallbackModelInput] = useState<string>('');
  const [activeModelError, setActiveModelError] = useState<string | null>(null);
  const [fallbackModelError, setFallbackModelError] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(() => Boolean(initialToken?.trim()));
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isColdStarting, setIsColdStarting] = useState<boolean>(false);

  const [errorState, setErrorState] = useState<ErrorBannerState | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [copiedTraceId, setCopiedTraceId] = useState<boolean>(false);

  const modalRef = useRef<HTMLDivElement>(null);
  const previousActiveElementRef = useRef<HTMLElement | null>(null);
  const coldStartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isSavingRef = useRef<boolean>(false);

  // Clear timers on unmount
  useEffect(() => {
    return () => {
      if (coldStartTimerRef.current) clearTimeout(coldStartTimerRef.current);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      if (successTimerRef.current) clearTimeout(successTimerRef.current);
    };
  }, []);

  // Fetch settings handler (for user actions)
  const fetchSettings = useCallback(async (authToken: string) => {
    setIsLoading(true);
    setErrorState(null);
    setSuccessMessage(null);
    setIsColdStarting(false);

    if (coldStartTimerRef.current) {
      clearTimeout(coldStartTimerRef.current);
    }
    coldStartTimerRef.current = setTimeout(() => {
      setIsColdStarting(true);
    }, 3000);

    try {
      const data = await adminApi.getSettings(authToken);
      setSettings(data);
      setActiveModelInput(data.activeModel);
      setFallbackModelInput(data.fallbackModel);
      setActiveModelError(null);
      setFallbackModelError(null);
      setIsAuthenticated(true);
      setToken(authToken);
    } catch (err: unknown) {
      const pd = toProblemDetails(err);
      const traceId = extractTraceId(err) || pd.traceId;
      const is401 = pd.status === 401;

      setIsAuthenticated(false);
      setSettings(null);

      setErrorState({
        title: is401 ? 'Unauthorized: Invalid or missing admin token' : (pd.title || 'Error Loading Settings'),
        detail: pd.detail || (is401 ? 'Missing, invalid, or expired authentication token.' : 'Failed to retrieve settings.'),
        traceId,
        status: pd.status,
        isAuthError: is401,
      });
    } finally {
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current);
        coldStartTimerRef.current = null;
      }
      setIsColdStarting(false);
      setIsLoading(false);
    }
  }, []);

  // On mount with initialToken or when initialToken changes
  useEffect(() => {
    if (!initialToken || !initialToken.trim()) return;
    const tokenToFetch = initialToken.trim();
    let isCurrent = true;

    if (coldStartTimerRef.current) {
      clearTimeout(coldStartTimerRef.current);
    }
    coldStartTimerRef.current = setTimeout(() => {
      if (isCurrent) {
        setIsColdStarting(true);
      }
    }, 3000);

    adminApi
      .getSettings(tokenToFetch)
      .then((data) => {
        if (!isCurrent) return;
        if (coldStartTimerRef.current) {
          clearTimeout(coldStartTimerRef.current);
          coldStartTimerRef.current = null;
        }
        setIsColdStarting(false);
        setIsLoading(false);
        setSettings(data);
        setActiveModelInput(data.activeModel);
        setFallbackModelInput(data.fallbackModel);
        setActiveModelError(null);
        setFallbackModelError(null);
        setIsAuthenticated(true);
        setToken(tokenToFetch);
      })
      .catch((err: unknown) => {
        if (!isCurrent) return;
        if (coldStartTimerRef.current) {
          clearTimeout(coldStartTimerRef.current);
          coldStartTimerRef.current = null;
        }
        setIsColdStarting(false);
        setIsLoading(false);
        const pd = toProblemDetails(err);
        const traceId = extractTraceId(err) || pd.traceId;
        const is401 = pd.status === 401;

        setIsAuthenticated(false);
        setSettings(null);

        setErrorState({
          title: is401
            ? 'Unauthorized: Invalid or missing admin token'
            : pd.title || 'Error Loading Settings',
          detail:
            pd.detail ||
            (is401
              ? 'Missing, invalid, or expired authentication token.'
              : 'Failed to retrieve settings.'),
          traceId,
          status: pd.status,
          isAuthError: is401,
        });
      });

    return () => {
      isCurrent = false;
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current);
      }
    };
  }, [initialToken]);

  // Focus trapping and modal Escape key listener
  useEffect(() => {
    if (isOpen === false) return;

    if (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement) {
      previousActiveElementRef.current = document.activeElement;
    }

    const focusTimer = setTimeout(() => {
      if (!modalRef.current) return;
      const focusable = modalRef.current.querySelector<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      focusable?.focus();
    }, 0);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose?.();
        return;
      }

      if (e.key === 'Tab' && modalRef.current) {
        const focusables = Array.from(
          modalRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
        );

        if (focusables.length === 0) {
          e.preventDefault();
          return;
        }

        const firstElement = focusables[0];
        const lastElement = focusables[focusables.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            e.preventDefault();
            lastElement.focus();
          }
        } else {
          if (document.activeElement === lastElement) {
            e.preventDefault();
            firstElement.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      clearTimeout(focusTimer);
      window.removeEventListener('keydown', handleKeyDown);
      if (previousActiveElementRef.current && typeof previousActiveElementRef.current.focus === 'function') {
        previousActiveElementRef.current.focus();
      }
    };
  }, [isOpen, onClose]);

  // Authenticate submission in locked state
  const handleAuthenticateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = tokenInput.trim();
    if (!trimmed) return;
    fetchSettings(trimmed);
  };

  // Lock / clear token
  const handleLockAndClearToken = () => {
    setToken('');
    setTokenInput('');
    setIsAuthenticated(false);
    setSettings(null);
    setErrorState(null);
    setSuccessMessage(null);
    setActiveModelInput('');
    setFallbackModelInput('');
    setActiveModelError(null);
    setFallbackModelError(null);
  };

  // Model input change handlers
  const handleActiveModelChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setActiveModelInput(val);
    if (val.trim()) {
      setActiveModelError(validateModelName(val));
    } else {
      setActiveModelError('Model name is required.');
    }
    if (successMessage) setSuccessMessage(null);
  };

  const handleFallbackModelChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setFallbackModelInput(val);
    if (val.trim()) {
      setFallbackModelError(validateModelName(val));
    } else {
      setFallbackModelError('Model name is required.');
    }
    if (successMessage) setSuccessMessage(null);
  };

  // Reset inputs to currently saved settings
  const handleReset = () => {
    if (!settings) return;
    setActiveModelInput(settings.activeModel);
    setFallbackModelInput(settings.fallbackModel);
    setActiveModelError(null);
    setFallbackModelError(null);
    if (successMessage) setSuccessMessage(null);
  };

  // Apply model presets
  const applyPreset = (active: string, fallback: string) => {
    setActiveModelInput(active);
    setFallbackModelInput(fallback);
    setActiveModelError(validateModelName(active));
    setFallbackModelError(validateModelName(fallback));
    if (successMessage) setSuccessMessage(null);
  };

  // Save changes handler
  const trimmedActive = activeModelInput.trim();
  const trimmedFallback = fallbackModelInput.trim();

  const isBothEmpty = !trimmedActive && !trimmedFallback;
  const hasValidationError =
    Boolean(validateModelName(trimmedActive)) ||
    Boolean(validateModelName(trimmedFallback));

  const isUnchanged =
    settings !== null &&
    trimmedActive === settings.activeModel &&
    trimmedFallback === settings.fallbackModel;

  const isSaveDisabled =
    isBothEmpty ||
    hasValidationError ||
    isUnchanged ||
    isSaving ||
    isLoading;

  const handleSave = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isSaveDisabled || !settings || isSavingRef.current) return;

    isSavingRef.current = true;
    setIsSaving(true);
    setErrorState(null);
    setSuccessMessage(null);
    setIsColdStarting(false);

    if (coldStartTimerRef.current) {
      clearTimeout(coldStartTimerRef.current);
    }
    coldStartTimerRef.current = setTimeout(() => {
      setIsColdStarting(true);
    }, 3000);

    const payload: AdminSettingsUpdate = {};
    if (trimmedActive !== settings.activeModel) {
      payload.activeModel = trimmedActive;
    }
    if (trimmedFallback !== settings.fallbackModel) {
      payload.fallbackModel = trimmedFallback;
    }

    try {
      const updated = await adminApi.updateSettings(payload, token);
      setSettings(updated);
      setActiveModelInput(updated.activeModel);
      setFallbackModelInput(updated.fallbackModel);
      setActiveModelError(null);
      setFallbackModelError(null);
      setSuccessMessage('Model settings updated successfully. Takes effect on next report generation.');

      if (successTimerRef.current) clearTimeout(successTimerRef.current);
      successTimerRef.current = setTimeout(() => {
        setSuccessMessage(null);
      }, 6000);
    } catch (err: unknown) {
      const pd = toProblemDetails(err);
      const traceId = extractTraceId(err) || pd.traceId;

      let errorTitle = pd.title || 'Update Failed';
      if (pd.status === 401) {
        errorTitle = 'Unauthorized: Invalid or missing admin token';
      } else if (pd.status === 422) {
        errorTitle = 'Validation Error: Invalid model configuration';
      } else if (pd.status === 500) {
        errorTitle = 'Server Error: Failed to update model settings';
      }

      setErrorState({
        title: errorTitle,
        detail: pd.detail || 'Failed to update model settings.',
        traceId,
        status: pd.status,
        isAuthError: pd.status === 401,
      });
    } finally {
      if (coldStartTimerRef.current) {
        clearTimeout(coldStartTimerRef.current);
        coldStartTimerRef.current = null;
      }
      setIsColdStarting(false);
      setIsSaving(false);
      isSavingRef.current = false;
    }
  };

  // Copy trace ID handler
  const handleCopyTraceId = async () => {
    if (!errorState?.traceId) return;
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(errorState.traceId);
      }
      setCopiedTraceId(true);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedTraceId(false), 2000);
    } catch {
      // Ignore clipboard write failures in restricted environments
    }
  };

  if (isOpen === false) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm"
      data-testid="admin-panel-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose?.();
        }
      }}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="admin-panel-title"
        className={`bg-white rounded-lg border border-slate-200 shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto flex flex-col ${className}`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <Settings className="w-5 h-5 text-slate-700" aria-hidden="true" />
            <h2 id="admin-panel-title" className="text-lg font-bold text-slate-900">
              Admin Configuration Panel
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close admin panel"
            className="text-slate-400 hover:text-slate-600 p-1 rounded-md hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-slate-900 cursor-pointer"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 flex flex-col gap-6">
          {/* Cold-start notification */}
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

          {/* RFC 9457 Error Banner */}
          {errorState && (
            <div
              role="alert"
              aria-live="polite"
              className="flex flex-col gap-2 p-3.5 text-sm rounded-md bg-red-50 border border-red-300 text-red-800 font-semibold"
            >
              <div className="flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-red-700 flex-shrink-0 mt-0.5" aria-hidden="true" />
                <div className="flex-1">
                  <p className="font-semibold text-red-900">{errorState.title}</p>
                  {errorState.detail && (
                    <p className="text-xs text-red-800 font-normal mt-0.5">{errorState.detail}</p>
                  )}
                </div>
              </div>

              {errorState.traceId && (
                <div className="flex items-center gap-2 pl-6 pt-1">
                  <span className="font-mono text-xs font-semibold text-red-800">
                    Trace ID: {errorState.traceId}
                  </span>
                  <button
                    type="button"
                    onClick={handleCopyTraceId}
                    aria-label="Copy Trace ID"
                    className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded border border-red-300 bg-white text-red-700 hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 cursor-pointer"
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

              {errorState.status !== 401 && errorState.status !== 422 && (
                <div className="pl-6 pt-1">
                  <button
                    type="button"
                    onClick={() => {
                      if (!isAuthenticated) {
                        if (tokenInput.trim()) fetchSettings(tokenInput.trim());
                      } else {
                        handleSave();
                      }
                    }}
                    className="inline-flex items-center gap-1 px-3 py-1 text-xs font-semibold rounded bg-red-700 text-white hover:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-500 transition-colors cursor-pointer"
                  >
                    <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
                    <span>Retry</span>
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Success Notification */}
          {successMessage && (
            <div
              role="status"
              aria-live="polite"
              className="flex items-center gap-2 p-3 text-sm font-semibold rounded-md bg-emerald-50 border border-emerald-300 text-emerald-800"
            >
              <CheckCircle2 className="w-5 h-5 text-emerald-700 flex-shrink-0" aria-hidden="true" />
              <span>{successMessage}</span>
            </div>
          )}

          {/* State 1: Locked View (Not Authenticated) */}
          {!isAuthenticated ? (
            <div className="py-6 flex flex-col items-center text-center max-w-md mx-auto w-full">
              <div className="w-12 h-12 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center mb-4 text-slate-700">
                <Lock className="w-6 h-6 text-slate-700" aria-hidden="true" />
              </div>
              <h3 className="text-base font-bold text-slate-900 mb-1">
                Admin Authentication Required
              </h3>
              <p className="text-xs text-slate-600 mb-6">
                Enter plant administrator Bearer token to inspect and reconfigure Gemini model routing.
              </p>

              <form onSubmit={handleAuthenticateSubmit} className="w-full flex flex-col gap-4 text-left">
                <div>
                  <label htmlFor="admin-token-input" className="block text-xs font-semibold text-slate-700 mb-1">
                    Admin Bearer Token
                  </label>
                  <div className="relative">
                    <input
                      id="admin-token-input"
                      type={showToken ? 'text' : 'password'}
                      value={tokenInput}
                      onChange={(e) => setTokenInput(e.target.value)}
                      placeholder="Enter admin token (e.g. dev-admin-secret-key-12345)"
                      disabled={isLoading}
                      className="w-full px-3 py-2 pr-10 text-sm font-mono border rounded-md border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-900 bg-white"
                    />
                    <button
                      type="button"
                      onClick={() => setShowToken(!showToken)}
                      aria-label={showToken ? 'Hide admin token' : 'Show admin token'}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-500 hover:text-slate-700 cursor-pointer"
                    >
                      {showToken ? (
                        <EyeOff className="w-4 h-4" aria-hidden="true" />
                      ) : (
                        <Eye className="w-4 h-4" aria-hidden="true" />
                      )}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isLoading || !tokenInput.trim()}
                  aria-label="Unlock and authenticate"
                  className="inline-flex items-center justify-center px-4 py-2 text-sm font-semibold rounded-md shadow-sm bg-slate-900 text-white hover:bg-slate-800 disabled:bg-slate-300 disabled:text-slate-500 disabled:cursor-not-allowed transition-colors cursor-pointer"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-1.5 animate-spin" aria-hidden="true" />
                      <span>Loading model settings...</span>
                    </>
                  ) : (
                    <>
                      <Key className="w-4 h-4 mr-1.5" aria-hidden="true" />
                      <span>Unlock</span>
                    </>
                  )}
                </button>
              </form>
            </div>
          ) : (
            /* State 2: Authenticated View */
            <div className="flex flex-col gap-6">
              {/* Auth status bar */}
              <div className="flex items-center justify-between pb-3 border-b border-slate-200">
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300">
                  <CheckCircle2 className="w-4 h-4 text-emerald-700" aria-hidden="true" />
                  <span>Authenticated as Admin</span>
                </div>
                <button
                  type="button"
                  onClick={handleLockAndClearToken}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-400 transition-colors cursor-pointer"
                >
                  <Lock className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                  <span>Lock / Clear Token</span>
                </button>
              </div>

              {/* Current Model Configuration Cards */}
              {settings && (
                <div className="flex flex-col gap-2">
                  <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                    Current Model Configuration
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="p-3.5 rounded-lg border border-slate-200 bg-slate-50 flex flex-col gap-2">
                      <div className="flex items-center justify-between text-xs font-medium text-slate-500">
                        <span className="flex items-center gap-1">
                          <Zap className="w-3.5 h-3.5 text-emerald-600" aria-hidden="true" />
                          <span>Active Model</span>
                        </span>
                        <span className="text-[10px] uppercase font-bold text-emerald-700 tracking-wider">Live</span>
                      </div>
                      <div className="flex items-center">
                        <span className="inline-flex items-center px-2.5 py-1 rounded text-xs font-bold border bg-emerald-100 text-emerald-800 border-emerald-300 font-mono">
                          <Cpu className="w-3.5 h-3.5 mr-1.5 text-emerald-700" aria-hidden="true" />
                          {settings.activeModel}
                        </span>
                      </div>
                    </div>

                    <div className="p-3.5 rounded-lg border border-slate-200 bg-slate-50 flex flex-col gap-2">
                      <div className="flex items-center justify-between text-xs font-medium text-slate-500">
                        <span className="flex items-center gap-1">
                          <ShieldCheck className="w-3.5 h-3.5 text-slate-600" aria-hidden="true" />
                          <span>Fallback Model</span>
                        </span>
                        <span className="text-[10px] uppercase font-bold text-slate-600 tracking-wider">Standby</span>
                      </div>
                      <div className="flex items-center">
                        <span className="inline-flex items-center px-2.5 py-1 rounded text-xs font-medium border bg-slate-100 text-slate-800 border-slate-300 font-mono">
                          <RotateCcw className="w-3.5 h-3.5 mr-1.5 text-slate-600" aria-hidden="true" />
                          {settings.fallbackModel}
                        </span>
                      </div>
                    </div>
                  </div>
                  <p className="text-xs text-slate-600">
                    Active model handles primary generation. Fallback model is automatically engaged if the primary model fails or encounters a 404 outage.
                  </p>
                </div>
              )}

              {/* Model Settings Reconfiguration Form */}
              <form onSubmit={handleSave} className="flex flex-col gap-4 border-t border-slate-200 pt-5">
                <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Reconfigure Model Routing
                </h3>

                {/* Active Model Field */}
                <div>
                  <label htmlFor="active-model-input" className="block text-xs font-semibold text-slate-700 mb-1">
                    Active Model
                  </label>
                  <input
                    id="active-model-input"
                    name="activeModel"
                    type="text"
                    value={activeModelInput}
                    onChange={handleActiveModelChange}
                    placeholder="e.g. google/gemini-3.5-flash-lite"
                    disabled={isSaving || isLoading}
                    className={`w-full px-3 py-2 text-sm font-mono border rounded-md focus:outline-none focus:ring-2 focus:ring-slate-900 bg-white ${
                      activeModelError ? 'border-red-500 focus:ring-red-500' : 'border-slate-300'
                    }`}
                  />
                  {activeModelError && (
                    <p role="alert" className="text-xs text-red-600 font-medium mt-1 flex items-center gap-1">
                      <AlertCircle className="w-3.5 h-3.5 inline flex-shrink-0" aria-hidden="true" />
                      <span>{activeModelError}</span>
                    </p>
                  )}
                </div>

                {/* Fallback Model Field */}
                <div>
                  <label htmlFor="fallback-model-input" className="block text-xs font-semibold text-slate-700 mb-1">
                    Fallback Model
                  </label>
                  <input
                    id="fallback-model-input"
                    name="fallbackModel"
                    type="text"
                    value={fallbackModelInput}
                    onChange={handleFallbackModelChange}
                    placeholder="e.g. google/gemini-3.1-flash-lite"
                    disabled={isSaving || isLoading}
                    className={`w-full px-3 py-2 text-sm font-mono border rounded-md focus:outline-none focus:ring-2 focus:ring-slate-900 bg-white ${
                      fallbackModelError ? 'border-red-500 focus:ring-red-500' : 'border-slate-300'
                    }`}
                  />
                  {fallbackModelError && (
                    <p role="alert" className="text-xs text-red-600 font-medium mt-1 flex items-center gap-1">
                      <AlertCircle className="w-3.5 h-3.5 inline flex-shrink-0" aria-hidden="true" />
                      <span>{fallbackModelError}</span>
                    </p>
                  )}
                </div>

                {/* Action Buttons: Save & Reset */}
                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={handleReset}
                    disabled={isSaving || isLoading || isUnchanged}
                    className="inline-flex items-center px-3 py-2 text-xs font-semibold rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    <RotateCcw className="w-3.5 h-3.5 mr-1.5" aria-hidden="true" />
                    <span>Reset</span>
                  </button>

                  <button
                    type="submit"
                    disabled={isSaveDisabled}
                    className="inline-flex items-center justify-center px-4 py-2 text-xs font-semibold rounded-md shadow-sm bg-slate-900 text-white hover:bg-slate-800 disabled:bg-slate-300 disabled:text-slate-500 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    {isSaving ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" aria-hidden="true" />
                        <span>Saving...</span>
                      </>
                    ) : (
                      <>
                        <Save className="w-3.5 h-3.5 mr-1.5" aria-hidden="true" />
                        <span>Save Changes</span>
                      </>
                    )}
                  </button>
                </div>

                {/* Preset Buttons */}
                <div className="flex flex-wrap items-center gap-2 pt-4 border-t border-slate-200">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider mr-1">
                    Presets:
                  </span>
                  <button
                    type="button"
                    onClick={() => applyPreset('google/gemini-3.5-flash-lite', 'google/gemini-3.1-flash-lite')}
                    disabled={isSaving || isLoading}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded border border-slate-300 bg-slate-50 text-slate-700 hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-400 transition-colors cursor-pointer"
                  >
                    <Cpu className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                    <span>Default Models</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => applyPreset('google/gemini-2.5-flash-lite-retired', 'google/gemini-3.5-flash-lite')}
                    disabled={isSaving || isLoading}
                    aria-label="Simulate Incident"
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-500 transition-colors cursor-pointer"
                  >
                    <ShieldAlert className="w-3.5 h-3.5 text-amber-600" aria-hidden="true" />
                    <span>Simulate Incident (Retired 404)</span>
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default AdminPanel;
