import React from 'react';
import {
  FileText,
  ShieldAlert,
  CheckCircle2,
  AlertCircle,
  User,
  Clock,
  Cpu,
  Tag,
  RefreshCw,
  FileSpreadsheet,
  CheckSquare,
} from 'lucide-react';
import type { ReportResponse } from '../types/api';
import { type ApiError, toProblemDetails, extractTraceId } from '../services/errors';

export interface ReportViewProps {
  report?: ReportResponse | null;
  isLoading?: boolean;
  error?: Error | ApiError | null;
  onRetry?: () => void;
  shiftKey?: string;
  className?: string;
}

/**
 * Resolves high-contrast action priority badge styling according to design system tokens.
 */
function getPriorityBadgeClass(priority: string | undefined): string {
  if (!priority) {
    return 'text-slate-600 bg-slate-50 border-slate-200';
  }
  switch (priority.toLowerCase()) {
    case 'high':
      return 'text-red-700 bg-red-50 border-red-200 font-bold';
    case 'medium':
      return 'text-amber-700 bg-amber-50 border-amber-200 font-medium';
    case 'low':
      return 'text-slate-600 bg-slate-50 border-slate-200';
    default:
      return 'text-slate-600 bg-slate-50 border-slate-200';
  }
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

export const ReportView: React.FC<ReportViewProps> = ({
  report,
  isLoading = false,
  error = null,
  onRetry,
  shiftKey,
  className = '',
}) => {
  // 1. Loading State with Skeletons
  if (isLoading) {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-busy="true"
        aria-label="Loading handover report..."
        className={`space-y-6 animate-pulse ${className}`.trim()}
        data-testid="report-view-loading"
      >
        <span className="sr-only">Loading handover report...</span>

        {/* Skeleton Metadata Bar */}
        <div
          data-testid="report-skeleton-metadata"
          className="p-4 bg-white border border-slate-200 rounded-lg flex flex-wrap gap-3 items-center"
        >
          <div className="h-6 w-24 bg-slate-200 rounded" />
          <div className="h-6 w-32 bg-slate-200 rounded" />
          <div className="h-6 w-44 bg-slate-200 rounded" />
          <div className="h-6 w-36 bg-slate-200 rounded" />
          <div className="h-6 w-28 bg-slate-200 rounded" />
        </div>

        {/* Skeleton Executive Summary */}
        <div
          data-testid="report-skeleton-summary"
          className="p-5 bg-white border border-slate-200 rounded-lg space-y-3"
        >
          <div className="h-6 w-44 bg-slate-200 rounded" />
          <div className="space-y-2">
            <div className="h-4 bg-slate-200 rounded w-full" />
            <div className="h-4 bg-slate-200 rounded w-5/6" />
            <div className="h-4 bg-slate-200 rounded w-4/6" />
          </div>
        </div>

        {/* Skeleton Safety Notes */}
        <div
          data-testid="report-skeleton-safety"
          className="p-5 bg-red-50 border border-red-200 rounded-lg space-y-3"
        >
          <div className="h-6 w-36 bg-red-200 rounded" />
          <div className="space-y-2">
            <div className="h-4 bg-red-200 rounded w-4/5" />
            <div className="h-4 bg-red-200 rounded w-3/4" />
          </div>
        </div>

        {/* Skeleton Action Items Table */}
        <div
          data-testid="report-skeleton-actions"
          className="p-5 bg-white border border-slate-200 rounded-lg space-y-3"
        >
          <div className="h-6 w-32 bg-slate-200 rounded" />
          <div className="border border-slate-200 rounded-lg overflow-hidden">
            <div className="h-10 bg-slate-100" />
            <div className="divide-y divide-slate-200">
              <div className="h-12 bg-white" />
              <div className="h-12 bg-white" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 2. Error State with Retry Action
  if (error) {
    const problem = toProblemDetails(error);
    const traceId = extractTraceId(error) ?? problem.traceId;
    const detailMessage =
      problem.detail ||
      (error instanceof Error ? error.message : 'An unexpected error occurred while loading the report.');

    return (
      <div
        role="alert"
        aria-live="polite"
        className={`flex flex-col items-center justify-center p-8 text-center bg-red-50 border border-red-300 rounded-lg text-red-900 space-y-3 ${className}`.trim()}
      >
        <AlertCircle className="w-8 h-8 text-red-600 flex-shrink-0" aria-hidden="true" />
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-red-900">Failed to load handover report</h2>
          <p className="text-sm text-red-700 max-w-lg break-words">{detailMessage}</p>
          {traceId && (
            <p className="text-xs font-mono text-red-600 mt-1">Trace ID: {traceId}</p>
          )}
        </div>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center px-4 py-2 text-sm font-semibold rounded-md shadow-sm bg-red-600 text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 transition-colors cursor-pointer mt-2"
          >
            <RefreshCw className="w-4 h-4 mr-2" aria-hidden="true" />
            Retry
          </button>
        )}
      </div>
    );
  }

  // 3. Empty State (no report available)
  if (!report) {
    return (
      <div
        role="status"
        aria-live="polite"
        className={`flex flex-col items-center justify-center p-8 text-center bg-slate-50 border border-slate-200 rounded-lg text-slate-600 space-y-2 ${className}`.trim()}
      >
        <FileSpreadsheet className="w-10 h-10 text-slate-400 mb-2" aria-hidden="true" />
        <h2 className="text-base font-semibold text-slate-800">
          {shiftKey
            ? `No report generated for shift ${shiftKey}.`
            : 'No handover report generated for this shift yet.'}
        </h2>
        <p className="text-sm text-slate-500 max-w-md">
          Log shift events and click &apos;Generate Handover&apos; to create a synthesized report.
        </p>
      </div>
    );
  }

  // 4. Report View: Defensive array extraction
  const safetyNotes = report.safetyNotes ?? [];
  const openActions = report.openActions ?? [];
  const summaryText = report.summary?.trim();

  return (
    <div
      className={`space-y-6 ${className}`.trim()}
      data-testid="report-view"
    >
      {/* Generation Metadata Bar */}
      <div
        data-testid="report-metadata-bar"
        className="p-4 bg-slate-50 border border-slate-200 rounded-lg flex flex-wrap items-center gap-2.5 text-xs text-slate-700"
      >
        {/* Version Badge */}
        <span className="inline-flex items-center px-2.5 py-1 rounded text-xs font-semibold border bg-slate-100 text-slate-800 border-slate-300">
          Version {report.version}
        </span>

        {/* Shift Key Badge */}
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-mono border bg-slate-100 text-slate-800 border-slate-300">
          <Tag className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
          {report.shiftKey}
        </span>

        {/* Model Used Badge */}
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border bg-slate-100 text-slate-800 border-slate-300">
          <Cpu className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
          {report.modelUsed}
        </span>

        {/* Generation Timestamp */}
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border bg-slate-100 text-slate-800 border-slate-300">
          <Clock className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
          {formatReportDate(report.createdAt)}
        </span>

        {/* Event Count Badge */}
        <span className="inline-flex items-center px-2.5 py-1 rounded text-xs font-medium border bg-slate-100 text-slate-800 border-slate-300">
          {report.eventCount} events synthesized
        </span>

        {/* Report ID */}
        <span
          className="inline-flex items-center ml-auto font-mono text-xs text-slate-500"
          title={report.id}
        >
          ID: {report.id}
        </span>
      </div>

      {/* Executive Summary Section */}
      <section
        aria-labelledby="executive-summary-heading"
        className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm space-y-3"
      >
        <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
          <FileText className="w-5 h-5 text-slate-700 flex-shrink-0" aria-hidden="true" />
          <h2 id="executive-summary-heading" className="text-lg font-bold text-slate-900">
            Executive Summary
          </h2>
        </div>
        {summaryText ? (
          <div className="text-sm text-slate-800 whitespace-pre-wrap break-words leading-relaxed">
            {report.summary}
          </div>
        ) : (
          <p className="text-sm text-slate-500 italic">No executive summary provided.</p>
        )}
      </section>

      {/* Safety Notes Section (Zero-Omission Safety Callout) */}
      {safetyNotes.length > 0 ? (
        <section
          aria-labelledby="safety-notes-heading"
          className="bg-red-50 border border-red-300 text-red-900 rounded-lg p-5 shadow-sm space-y-3"
        >
          <div className="flex items-center gap-2 border-b border-red-200 pb-3">
            <ShieldAlert className="w-5 h-5 text-red-700 flex-shrink-0" aria-hidden="true" />
            <h2 id="safety-notes-heading" className="text-lg font-bold text-red-900">
              Safety Notes
            </h2>
          </div>
          <ul className="space-y-2 list-disc list-inside text-sm text-red-950 font-medium">
            {safetyNotes.map((note, index) => (
              <li key={index} className="break-words leading-relaxed">
                {note}
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <section
          aria-labelledby="safety-notes-heading"
          className="bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg p-5 shadow-sm space-y-3"
        >
          <div className="flex items-center gap-2 border-b border-emerald-200/60 pb-3">
            <ShieldAlert className="w-5 h-5 text-emerald-700 flex-shrink-0" aria-hidden="true" />
            <h2 id="safety-notes-heading" className="text-lg font-bold text-emerald-900">
              Safety Notes
            </h2>
          </div>
          <div className="flex items-center gap-2 text-sm text-emerald-800 font-medium">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" aria-hidden="true" />
            <span>No safety incidents or hazards flagged for this shift.</span>
          </div>
        </section>
      )}

      {/* Open Actions Section */}
      <section
        aria-labelledby="open-actions-heading"
        className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm space-y-3"
      >
        <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
          <CheckSquare className="w-5 h-5 text-slate-700 flex-shrink-0" aria-hidden="true" />
          <h2 id="open-actions-heading" className="text-lg font-bold text-slate-900">
            Open Actions
          </h2>
        </div>

        {openActions.length > 0 ? (
          <div className="overflow-x-auto border border-slate-200 rounded-lg">
            <table className="min-w-full divide-y divide-slate-200 text-left">
              <thead className="bg-slate-50">
                <tr>
                  <th
                    scope="col"
                    className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider w-28"
                  >
                    Priority
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider"
                  >
                    Action Item
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-3 text-xs font-bold text-slate-700 uppercase tracking-wider w-48"
                  >
                    Owner
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 bg-white">
                {openActions.map((actionItem, index) => (
                  <tr key={index} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs uppercase border ${getPriorityBadgeClass(
                          actionItem.priority
                        )}`}
                      >
                        {actionItem.priority}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-900 break-words leading-relaxed">
                      {actionItem.action}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-700 whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <User className="w-4 h-4 text-slate-400 flex-shrink-0" aria-hidden="true" />
                        <span className="break-words font-medium">{actionItem.owner}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-4 text-center bg-slate-50 border border-slate-200 rounded-lg text-slate-500 text-sm">
            No open action items pending for oncoming shift.
          </div>
        )}
      </section>
    </div>
  );
};

export default ReportView;
