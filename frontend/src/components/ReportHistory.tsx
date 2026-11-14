import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  History,
  Clock,
  Cpu,
  ChevronRight,
  Copy,
  Check,
  RotateCcw,
  Columns,
  Inbox,
  AlertCircle,
  Database,
} from 'lucide-react';
import type { ReportResponse, ReportSummary } from '../types/api';
import {
  reportsApi,
  type ApiError,
  type RequestConfig,
  toProblemDetails,
  extractTraceId,
} from '../services';
import { ReportDetail, type ReportDetailProps } from './ReportDetail';

export { ReportDetail, type ReportDetailProps };

export interface ReportHistoryProps {
  /** Optional shift identifier filter in YYYY-MM-DD-(early|late|night) format */
  shiftKey?: string;
  /** Optional pre-selected report UUID to inspect */
  initialSelectedId?: string;
  /** Optional callback when a report version is selected */
  onSelectReport?: (report: ReportResponse | ReportSummary) => void;
  /** Optional container CSS class name */
  className?: string;
}

interface ReportsApiWithDetail {
  getReportDetail?: (id: string, config?: RequestConfig) => Promise<ReportResponse>;
  getReport: (id: string, config?: RequestConfig) => Promise<ReportResponse>;
}

// Ensure reportsApi.getReportDetail is defined so tests can spyOn(reportsApi, 'getReportDetail')
if (typeof (reportsApi as ReportsApiWithDetail).getReportDetail !== 'function') {
  (reportsApi as ReportsApiWithDetail).getReportDetail = (id: string, config?: RequestConfig) =>
    reportsApi.getReport(id, config);
}

/**
 * Resolves full immutable report detail snapshot via getReportDetail or fallback getReport.
 */
async function fetchReportDetail(id: string): Promise<ReportResponse> {
  const api = reportsApi as ReportsApiWithDetail;
  if (typeof api.getReportDetail === 'function') {
    return api.getReportDetail(id);
  }
  return api.getReport(id);
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
 * High-contrast, accessible Report History component.
 * Allows operators to browse report versions for a shift and inspect immutable
 * past version snapshots side-by-side with the latest report version.
 */
export const ReportHistory: React.FC<ReportHistoryProps> = ({
  shiftKey,
  initialSelectedId,
  onSelectReport,
  className = '',
}) => {
  const [summaries, setSummaries] = useState<ReportSummary[]>([]);
  const [isListLoading, setIsListLoading] = useState(true);
  const [listError, setListError] = useState<Error | ApiError | null>(null);
  const [isListColdStarting, setIsListColdStarting] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId ?? null);
  const [selectedReport, setSelectedReport] = useState<ReportResponse | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<Error | ApiError | null>(null);
  const [isDetailColdStarting, setIsDetailColdStarting] = useState(false);

  const [isComparisonMode, setIsComparisonMode] = useState(false);
  const [latestReportSnapshot, setLatestReportSnapshot] = useState<ReportResponse | null>(null);

  const [copiedTraceId, setCopiedTraceId] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);

  const listColdStartTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const detailColdStartTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeDetailRequestIdRef = useRef(0);
  const reportsCacheRef = useRef<Map<string, ReportResponse>>(new Map());

  // Reset shift-specific states on shiftKey change during render
  const [prevShiftKey, setPrevShiftKey] = useState(shiftKey);
  if (shiftKey !== prevShiftKey) {
    setPrevShiftKey(shiftKey);
    setIsListLoading(true);
    setListError(null);
    setSummaries([]);
    setSelectedReport(null);
    setSelectedId(null);
    setIsComparisonMode(false);
    setLatestReportSnapshot(null);
  }

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (listColdStartTimeoutRef.current) clearTimeout(listColdStartTimeoutRef.current);
      if (detailColdStartTimeoutRef.current) clearTimeout(detailColdStartTimeoutRef.current);
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    };
  }, []);

  const handleCopyTraceId = (traceId: string) => {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(traceId);
    }
    setCopiedTraceId(true);
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    copyTimeoutRef.current = setTimeout(() => {
      setCopiedTraceId(false);
    }, 2000);
  };

  /**
   * Loads full immutable detail snapshot by report ID with race-condition protection.
   */
  const loadDetail = useCallback(
    (id: string, isLatestVersion = false) => {
      const requestId = ++activeDetailRequestIdRef.current;

      if (detailColdStartTimeoutRef.current) {
        clearTimeout(detailColdStartTimeoutRef.current);
      }
      setIsDetailColdStarting(false);
      setIsDetailLoading(true);
      setDetailError(null);

      // Start 3000ms cold-start timer
      detailColdStartTimeoutRef.current = setTimeout(() => {
        if (activeDetailRequestIdRef.current === requestId) {
          setIsDetailColdStarting(true);
        }
      }, 3000);

      fetchReportDetail(id)
        .then((detail) => {
          // Discard stale responses from rapid selection clicks
          if (activeDetailRequestIdRef.current !== requestId) {
            return;
          }

          if (detailColdStartTimeoutRef.current) {
            clearTimeout(detailColdStartTimeoutRef.current);
          }
          setIsDetailColdStarting(false);
          setIsDetailLoading(false);
          setSelectedReport(detail);
          reportsCacheRef.current.set(detail.id, detail);

          if (isLatestVersion) {
            setLatestReportSnapshot(detail);
          }

          onSelectReport?.(detail);
        })
        .catch((err: unknown) => {
          if (activeDetailRequestIdRef.current !== requestId) {
            return;
          }
          if (detailColdStartTimeoutRef.current) {
            clearTimeout(detailColdStartTimeoutRef.current);
          }
          setIsDetailColdStarting(false);
          setIsDetailLoading(false);
          setDetailError(err instanceof Error ? err : new Error(String(err)));
        });
    },
    [onSelectReport]
  );

  // Fetch report list whenever shiftKey or retryNonce changes
  useEffect(() => {
    let isCurrent = true;

    if (listColdStartTimeoutRef.current) {
      clearTimeout(listColdStartTimeoutRef.current);
    }

    // Start 3000ms cold-start timer for list fetch
    listColdStartTimeoutRef.current = setTimeout(() => {
      if (isCurrent) {
        setIsListColdStarting(true);
      }
    }, 3000);

    reportsApi
      .listReports(shiftKey, 20)
      .then((data) => {
        if (!isCurrent) return;

        if (listColdStartTimeoutRef.current) {
          clearTimeout(listColdStartTimeoutRef.current);
        }
        setIsListColdStarting(false);
        setIsListLoading(false);

        // Order descending by version number (v3, v2, v1)
        const sorted = [...data].sort((a, b) => b.version - a.version);
        setSummaries(sorted);

        if (sorted.length > 0) {
          const latest = sorted[0];
          const target = initialSelectedId
            ? sorted.find((s) => s.id === initialSelectedId) ?? latest
            : latest;

          setSelectedId(target.id);
          onSelectReport?.(target);
          loadDetail(target.id, target.id === latest.id);

          // Pre-fetch latest report for comparison if target is not the latest version
          if (target.id !== latest.id) {
            fetchReportDetail(latest.id)
              .then((latestDetail) => {
                if (!isCurrent) return;
                reportsCacheRef.current.set(latestDetail.id, latestDetail);
                setLatestReportSnapshot(latestDetail);
              })
              .catch(() => {
                // Ignore background latest fetch errors
              });
          }
        }
      })
      .catch((err: unknown) => {
        if (!isCurrent) return;
        if (listColdStartTimeoutRef.current) {
          clearTimeout(listColdStartTimeoutRef.current);
        }
        setIsListColdStarting(false);
        setIsListLoading(false);
        setListError(err instanceof Error ? err : new Error(String(err)));
      });

    return () => {
      isCurrent = false;
      if (listColdStartTimeoutRef.current) {
        clearTimeout(listColdStartTimeoutRef.current);
      }
    };
  }, [shiftKey, initialSelectedId, retryNonce, onSelectReport, loadDetail]);

  // Handle manual version selection from history list
  const handleSelectVersion = (summary: ReportSummary) => {
    if (summary.id === selectedId) return;

    setSelectedId(summary.id);
    onSelectReport?.(summary);

    const latest = summaries[0];
    const isLatest = latest && summary.id === latest.id;
    loadDetail(summary.id, isLatest);

    // If latest snapshot is not loaded yet and we're selecting an older version
    if (!isLatest && latest && !latestReportSnapshot) {
      if (reportsCacheRef.current.has(latest.id)) {
        setLatestReportSnapshot(reportsCacheRef.current.get(latest.id)!);
      } else {
        fetchReportDetail(latest.id)
          .then((latestDetail) => {
            reportsCacheRef.current.set(latestDetail.id, latestDetail);
            setLatestReportSnapshot(latestDetail);
          })
          .catch(() => {
            // Ignore
          });
      }
    }
  };

  const handleRetryList = () => {
    setIsListLoading(true);
    setListError(null);
    setRetryNonce((n) => n + 1);
  };

  const handleRetryDetail = () => {
    if (selectedId) {
      const latest = summaries[0];
      loadDetail(selectedId, latest && selectedId === latest.id);
    }
  };

  const latestSummary = summaries[0];
  const isSelectedHistorical = Boolean(
    selectedReport && latestSummary && selectedReport.version < latestSummary.version
  ) || Boolean(
    !selectedReport && selectedId && latestSummary && selectedId !== latestSummary.id
  );
  const hasMultipleVersions = summaries.length > 1;
  const canCompare = hasMultipleVersions && isSelectedHistorical;

  const showColdStartBanner = isListColdStarting || isDetailColdStarting;

  return (
    <div
      data-testid="report-history"
      className={`space-y-6 ${className}`.trim()}
    >
      {/* Header and Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <History className="w-6 h-6 text-slate-800" aria-hidden="true" />
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">Report History</h2>
          </div>
          <p className="text-sm text-slate-600 mt-1">
            {shiftKey ? (
              <span>
                Historical shift handover reports for shift{' '}
                <span className="font-mono font-semibold text-slate-800">{shiftKey}</span>.
              </span>
            ) : (
              'Browse and inspect historical shift handover reports across all shifts.'
            )}
          </p>
        </div>

        {/* Side-by-Side Comparison Toggle */}
        <div className="flex items-center gap-2">
          {hasMultipleVersions ? (
            canCompare && (
              <button
                type="button"
                onClick={() => setIsComparisonMode(!isComparisonMode)}
                aria-pressed={isComparisonMode}
                aria-label={isComparisonMode ? 'Switch to single snapshot view' : 'Switch to side-by-side comparison'}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-md border border-slate-300 bg-white hover:bg-slate-50 text-slate-800 shadow-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-900 cursor-pointer"
              >
                <Columns className="w-4 h-4 text-slate-600" aria-hidden="true" />
                <span>{isComparisonMode ? 'Single snapshot view' : 'Side-by-side comparison'}</span>
              </button>
            )
          ) : summaries.length === 1 ? (
            <div
              role="note"
              data-testid="single-version-guard"
              className="text-xs text-slate-500 italic max-w-xs"
              title="Only one version exists for this shift. Regenerate to create version 2."
            >
              Only one version exists for this shift. Regenerate to create version 2.
            </div>
          ) : null}
        </div>
      </div>

      {/* Cold-Start Progress UX (when request exceeds 3000ms) */}
      {showColdStartBanner && (
        <div
          role="status"
          aria-live="polite"
          data-testid="cold-start-banner"
          className="flex items-center gap-3 p-4 text-sm rounded-lg bg-amber-50 border border-amber-300 text-amber-900 shadow-sm"
        >
          <Database className="w-5 h-5 text-amber-700 flex-shrink-0 animate-pulse" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-bold text-xs uppercase tracking-wider text-amber-800">
              Cold Start In Progress
            </p>
            <p className="text-sm text-amber-900 mt-0.5">
              Waking up the database — the first request after an idle period may take up to 20 s.
            </p>
          </div>
        </div>
      )}

      {/* List Loading Skeletons */}
      {isListLoading && (
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          aria-label="Loading report history..."
          data-testid="history-list-loading"
          className="space-y-3 animate-pulse"
        >
          <span className="sr-only">Loading report history...</span>
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="p-4 bg-white border border-slate-200 rounded-lg flex items-center justify-between"
            >
              <div className="space-y-2 flex-1">
                <div className="flex gap-2">
                  <div className="h-5 w-16 bg-slate-200 rounded" />
                  <div className="h-5 w-28 bg-slate-200 rounded" />
                </div>
                <div className="flex gap-4">
                  <div className="h-4 w-32 bg-slate-200 rounded" />
                  <div className="h-4 w-40 bg-slate-200 rounded" />
                  <div className="h-4 w-24 bg-slate-200 rounded" />
                </div>
              </div>
              <div className="h-6 w-6 bg-slate-200 rounded-full ml-4" />
            </div>
          ))}
        </div>
      )}

      {/* List Fetch Error Banner */}
      {listError && (
        <div
          role="alert"
          aria-live="assertive"
          data-testid="history-list-error"
          className="flex flex-col gap-3 p-5 rounded-lg bg-red-50 border border-red-300 text-red-900 shadow-sm"
        >
          <div className="flex items-start gap-3">
            <AlertCircle className="w-6 h-6 text-red-700 flex-shrink-0 mt-0.5" aria-hidden="true" />
            <div className="flex-1 space-y-1">
              <h3 className="text-base font-bold text-red-900">
                {toProblemDetails(listError).title || 'Failed to load report history'}
              </h3>
              <p className="text-sm text-red-700 break-words leading-relaxed">
                {toProblemDetails(listError).detail ||
                  (listError instanceof Error ? listError.message : 'An unexpected error occurred.')}
              </p>
            </div>
          </div>

          {extractTraceId(listError) && (
            <div className="flex items-center gap-2 pl-9 pt-1">
              <span className="font-mono text-xs font-semibold text-red-800">
                Trace ID: {extractTraceId(listError)}
              </span>
              <button
                type="button"
                onClick={() => handleCopyTraceId(extractTraceId(listError)!)}
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

          <div className="pl-9 pt-1">
            <button
              type="button"
              onClick={handleRetryList}
              className="inline-flex items-center px-3.5 py-1.5 text-xs font-semibold rounded bg-red-700 text-white hover:bg-red-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-red-600 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5 mr-1.5" aria-hidden="true" />
              <span>Try Again</span>
            </button>
          </div>
        </div>
      )}

      {/* Empty State (0 reports) */}
      {!isListLoading && !listError && summaries.length === 0 && (
        <div
          role="status"
          aria-live="polite"
          data-testid="empty-history-state"
          className="flex flex-col items-center justify-center p-12 text-center bg-slate-50 border border-slate-200 rounded-lg text-slate-600 space-y-3"
        >
          <Inbox className="w-12 h-12 text-slate-400 mb-1" aria-hidden="true" />
          <h3 className="text-base font-bold text-slate-900">No report history available</h3>
          <p className="text-sm text-slate-600 max-w-md">
            {shiftKey
              ? `No handover reports have been generated yet for shift ${shiftKey}.`
              : 'No handover reports have been generated yet.'}
          </p>
          <p className="text-xs text-slate-500 max-w-sm">
            Log shift events on the Shift Board and generate a handover report to begin version history tracking.
          </p>
        </div>
      )}

      {/* Report Version History List and Detail Sections */}
      {!isListLoading && !listError && summaries.length > 0 && (
        <div className="space-y-6">
          {/* Version History List */}
          <section
            aria-labelledby="report-history-versions-heading"
            className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm space-y-3"
          >
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 id="report-history-versions-heading" className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                Generated Versions ({summaries.length})
              </h3>
              <span className="text-xs text-slate-500">Ordered by most recent version</span>
            </div>

            <div
              role="list"
              aria-label="Report version history"
              className="space-y-2.5"
            >
              {summaries.map((summary, index) => {
                const isLatest = index === 0;
                const isSelected = summary.id === selectedId;

                return (
                  <div key={summary.id} role="listitem">
                    <button
                      type="button"
                      onClick={() => handleSelectVersion(summary)}
                      aria-selected={isSelected}
                      aria-label={`Version ${summary.version} for shift ${summary.shiftKey}`}
                      className={`w-full text-left p-4 rounded-lg border transition-all flex items-center justify-between gap-4 cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-900 ${
                        isSelected
                          ? 'ring-2 ring-slate-900 bg-slate-100 border-slate-400 shadow-sm'
                          : 'bg-white border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 flex-1 min-w-0">
                        {/* Version Badge */}
                        <div className="flex items-center gap-2">
                          <span
                            className={`inline-flex items-center px-2.5 py-1 rounded text-xs border ${
                              isLatest
                                ? 'bg-emerald-100 text-emerald-800 border-emerald-300 font-bold'
                                : 'bg-slate-100 text-slate-700 border-slate-300 font-medium'
                            }`}
                          >
                            v{summary.version}
                            {isLatest && <span className="ml-1.5 text-[10px] uppercase font-bold tracking-wider">(Latest)</span>}
                          </span>

                          {/* Shift Key Badge */}
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-slate-100 text-slate-800 border border-slate-200">
                            {summary.shiftKey}
                          </span>
                        </div>

                        {/* Metadata items */}
                        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
                          {/* Timestamp with Clock Icon */}
                          <span className="inline-flex items-center gap-1.5">
                            <Clock className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" aria-hidden="true" />
                            <span>{formatReportDate(summary.createdAt)}</span>
                          </span>

                          {/* Model Used Badge with Bot/Cpu Icon */}
                          <span className="inline-flex items-center gap-1.5 font-mono">
                            <Cpu className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" aria-hidden="true" />
                            <span>{summary.modelUsed}</span>
                          </span>

                          {/* Event Count Badge */}
                          <span className="inline-flex items-center px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                            {summary.eventCount} events
                          </span>
                        </div>
                      </div>

                      {/* Interactive Selection Chevron */}
                      <ChevronRight
                        className={`w-5 h-5 flex-shrink-0 transition-transform ${
                          isSelected ? 'text-slate-900 translate-x-0.5' : 'text-slate-400'
                        }`}
                        aria-hidden="true"
                      />
                    </button>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Snapshot Inspection & Comparison Section */}
          <section
            aria-labelledby="snapshot-detail-section-heading"
            className="space-y-4"
          >
            <h3 id="snapshot-detail-section-heading" className="sr-only">
              Report Snapshot Detail
            </h3>

            {/* Side-by-Side Comparison Mode */}
            {isComparisonMode && canCompare && selectedReport && latestReportSnapshot ? (
              <div
                data-testid="side-by-side-comparison"
                className="grid grid-cols-1 lg:grid-cols-2 gap-4"
              >
                {/* Left Column: Historical Snapshot */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between pb-2 border-b border-amber-300">
                    <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                      <span>Selected Historical Snapshot (v{selectedReport.version})</span>
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-300">
                        Historical
                      </span>
                    </h4>
                  </div>
                  <ReportDetail
                    report={selectedReport}
                    isHistorical={true}
                    isLoading={isDetailLoading}
                    error={detailError}
                    onRetry={handleRetryDetail}
                  />
                </div>

                {/* Right Column: Current Latest Report */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between pb-2 border-b border-emerald-300">
                    <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                      <span>Current Latest Report (v{latestReportSnapshot.version})</span>
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">
                        Latest
                      </span>
                    </h4>
                  </div>
                  <ReportDetail
                    report={latestReportSnapshot}
                    isHistorical={false}
                  />
                </div>
              </div>
            ) : (
              /* Single Snapshot View */
              <ReportDetail
                report={selectedReport}
                isHistorical={isSelectedHistorical}
                isLoading={isDetailLoading}
                error={detailError}
                onRetry={handleRetryDetail}
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
};

export default ReportHistory;
