import React, { useState, useRef, useEffect } from 'react';
import {
  Lock,
  AlertCircle,
  Copy,
  Check,
  RotateCcw,
  FileSpreadsheet,
} from 'lucide-react';
import type { ReportResponse } from '../types/api';
import { type ApiError, toProblemDetails, extractTraceId } from '../services/errors';
import { ReportView } from './ReportView';

export interface ReportDetailProps {
  /** Immutable report snapshot to display */
  report?: ReportResponse | null;
  /** Loading state while fetching snapshot detail */
  isLoading?: boolean;
  /** Error state if report snapshot fetch failed */
  error?: Error | ApiError | null;
  /** Callback to retry fetching detail snapshot */
  onRetry?: () => void;
  /** Whether this snapshot is an older historical version vs the active latest version */
  isHistorical?: boolean;
  /** Optional container styling */
  className?: string;
}

/**
 * Formats ISO timestamp string to local plant date & time "YYYY-MM-DD HH:mm".
 */
function formatReportDate(isoString?: string): string {
  if (!isoString) return '';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
  } catch {
    return isoString;
  }
}

/**
 * High-contrast, read-only report detail view component.
 * Displays immutable past version snapshots or latest versions with safe text rendering.
 */
export const ReportDetail: React.FC<ReportDetailProps> = ({
  report,
  isLoading = false,
  error = null,
  onRetry,
  isHistorical = false,
  className = '',
}) => {
  const [copiedTraceId, setCopiedTraceId] = useState(false);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  const handleCopyTraceId = (traceId: string) => {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(traceId);
    }
    setCopiedTraceId(true);
    if (copyTimeoutRef.current) {
      clearTimeout(copyTimeoutRef.current);
    }
    copyTimeoutRef.current = setTimeout(() => {
      setCopiedTraceId(false);
    }, 2000);
  };

  // 1. Loading State
  if (isLoading) {
    return (
      <div
        data-testid="report-detail-loading"
        className={`space-y-4 ${className}`.trim()}
      >
        <ReportView isLoading={true} />
      </div>
    );
  }

  // 2. Error State with RFC 9457 Problem Details
  if (error) {
    const problem = toProblemDetails(error);
    const traceId = extractTraceId(error) ?? problem.traceId;
    const isNotFound =
      problem.status === 404 ||
      problem.title?.toLowerCase().includes('not found') ||
      problem.detail?.toLowerCase().includes('not found');
    const heading = isNotFound
      ? 'Report snapshot not found'
      : (problem.title && problem.title !== 'Error' && problem.title !== 'about:blank')
      ? problem.title
      : 'Failed to load report snapshot';
    const detailMessage =
      problem.detail ||
      (error instanceof Error ? error.message : 'An unexpected error occurred while loading the report snapshot.');

    return (
      <div
        role="alert"
        aria-live="assertive"
        data-testid="report-detail-error"
        className={`flex flex-col gap-3 p-5 rounded-lg bg-red-50 border border-red-300 text-red-900 shadow-sm ${className}`.trim()}
      >
        <div className="flex items-start gap-3">
          <AlertCircle className="w-6 h-6 text-red-700 flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div className="flex-1 space-y-1">
            <h3 className="text-base font-bold text-red-900">{heading}</h3>
            <p className="text-sm text-red-700 break-words leading-relaxed">{detailMessage}</p>
          </div>
        </div>

        {traceId && (
          <div className="flex items-center gap-2 pl-9 pt-1">
            <span className="font-mono text-xs font-semibold text-red-800">
              Trace ID: {traceId}
            </span>
            <button
              type="button"
              onClick={() => handleCopyTraceId(traceId)}
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

        {onRetry && (
          <div className="pl-9 pt-1">
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center px-3.5 py-1.5 text-xs font-semibold rounded bg-red-700 text-white hover:bg-red-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-red-600 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5 mr-1.5" aria-hidden="true" />
              <span>Try Again</span>
            </button>
          </div>
        )}
      </div>
    );
  }

  // 3. Empty State (no report selected)
  if (!report) {
    return (
      <div
        role="status"
        aria-live="polite"
        data-testid="report-detail-empty"
        className={`flex flex-col items-center justify-center p-8 text-center bg-slate-50 border border-slate-200 rounded-lg text-slate-600 space-y-2 ${className}`.trim()}
      >
        <FileSpreadsheet className="w-10 h-10 text-slate-400 mb-2" aria-hidden="true" />
        <h3 className="text-base font-semibold text-slate-800">No report snapshot selected</h3>
        <p className="text-sm text-slate-500 max-w-md">
          Select a report version from the history list to inspect its snapshot details.
        </p>
      </div>
    );
  }

  // 4. Report Snapshot Display
  return (
    <div
      data-testid="report-detail"
      className={`space-y-4 ${className}`.trim()}
    >
      {/* Historical Snapshot Banner */}
      {isHistorical && (
        <div
          role="status"
          data-testid="historical-version-banner"
          className="flex items-center gap-3 p-4 bg-amber-50 border border-amber-300 text-amber-900 rounded-lg shadow-sm"
        >
          <Lock className="w-5 h-5 text-amber-700 flex-shrink-0" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-semibold text-sm text-amber-900">
              Historical Version {report.version} Snapshot (Read-Only / Immutable)
            </p>
            <p className="text-xs text-amber-800 mt-0.5">
              This snapshot reflects the exact report content synthesized for shift {report.shiftKey} at {formatReportDate(report.createdAt)}.
            </p>
          </div>
        </div>
      )}

      {/* Full Report View */}
      <ReportView
        report={report}
        shiftKey={report.shiftKey}
      />
    </div>
  );
};

export default ReportDetail;
