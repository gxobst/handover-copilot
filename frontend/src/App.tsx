import { useState, useEffect, useCallback } from 'react';
import { ShiftSelector } from './components/ShiftSelector';
import { EventForm } from './components/EventForm';
import { EventList } from './components/EventList';
import { GenerateButton } from './components/GenerateButton';
import { ReportView } from './components/ReportView';
import { ReportHistory } from './components/ReportHistory';
import { AdminPanel, AdminPanelTrigger } from './components/AdminPanel';
import { ToastProvider, useToast } from './context/ToastContext';
import { ToastContainer } from './components/ToastContainer';
import { getDefaultShiftKey } from './utils/shiftKey';
import { eventsApi, reportsApi, type ApiError } from './services';
import type { ReportResponse, EventResponse } from './types/api';
import { LayoutDashboard, History } from 'lucide-react';

export function AppShell() {
  const [selectedShiftKey, setSelectedShiftKey] = useState<string>(() => getDefaultShiftKey());
  const [activeTab, setActiveTab] = useState<'board' | 'history'>('board');
  const [isAdminOpen, setIsAdminOpen] = useState<boolean>(false);
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [eventCount, setEventCount] = useState<number>(0);
  const [currentReport, setCurrentReport] = useState<ReportResponse | null>(null);

  const { showError } = useToast();

  // Load event count and latest report on shift change or refresh
  useEffect(() => {
    let isCurrent = true;

    eventsApi
      .listEvents(selectedShiftKey)
      .then((data) => {
        if (!isCurrent) return;
        setEventCount(Array.isArray(data) ? data.length : 0);
      })
      .catch(() => {
        if (!isCurrent) return;
        setEventCount(0);
      });

    reportsApi
      .listReports(selectedShiftKey)
      .then((summaries) => {
        if (!isCurrent) return;
        if (Array.isArray(summaries) && summaries.length > 0) {
          const latestSummary = summaries[0];
          reportsApi
            .getReport(latestSummary.id)
            .then((report) => {
              if (!isCurrent) return;
              setCurrentReport(report);
            })
            .catch(() => {
              if (!isCurrent) return;
              setCurrentReport(null);
            });
        } else {
          setCurrentReport(null);
        }
      })
      .catch(() => {
        if (!isCurrent) return;
        setCurrentReport(null);
      });

    return () => {
      isCurrent = false;
    };
  }, [selectedShiftKey, refreshKey]);

  const handleEventCreated = useCallback((_event: EventResponse) => {
    setRefreshKey((k) => k + 1);
    setEventCount((prev) => prev + 1);
  }, []);

  const handleEventDeleted = useCallback((_id: string) => {
    setRefreshKey((k) => k + 1);
    setEventCount((prev) => Math.max(0, prev - 1));
  }, []);

  const handleReportGenerated = useCallback((report: ReportResponse) => {
    setCurrentReport(report);
  }, []);

  const handleError = useCallback(
    (err: Error | ApiError | unknown) => {
      showError(err);
    },
    [showError]
  );

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans">
      {/* Top Header */}
      <header className="bg-slate-900 text-white border-b border-slate-800 px-6 py-4 shadow-sm sticky top-0 z-40">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <span
              className="inline-block w-3 h-3 rounded-full bg-emerald-500 animate-pulse flex-shrink-0"
              aria-hidden="true"
            />
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white">
                Shift Handover Copilot
              </h1>
              <p className="text-xs text-slate-400">
                AI-Powered Handover & Operational Incident Intelligence
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-xs uppercase tracking-wider text-slate-400 font-medium px-2.5 py-1 rounded border border-slate-700 bg-slate-800">
              Industrial Plant Edition
            </span>
            <AdminPanelTrigger onClick={() => setIsAdminOpen(true)} />
          </div>
        </div>

        {/* Global Nav Bar & Shift Selector */}
        <div className="max-w-7xl mx-auto mt-4 pt-3 border-t border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center space-x-2">
            <button
              type="button"
              onClick={() => setActiveTab('board')}
              className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-md text-sm font-semibold transition-colors ${
                activeTab === 'board'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800'
              }`}
            >
              <LayoutDashboard className="w-4 h-4" aria-hidden="true" />
              Shift Board
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('history')}
              className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-md text-sm font-semibold transition-colors ${
                activeTab === 'history'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800'
              }`}
            >
              <History className="w-4 h-4" aria-hidden="true" />
              Report History
            </button>
          </div>

          <div className="flex items-center gap-3">
            <ShiftSelector
              value={selectedShiftKey}
              onChange={setSelectedShiftKey}
            />
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        {/* Category Legend Bar per Design System */}
        <section
          aria-label="Category Legend"
          className="bg-white rounded-lg border border-slate-200 px-4 py-3 shadow-sm flex items-center justify-between flex-wrap gap-3"
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Event Categories:
            </span>
            <div className="flex flex-wrap gap-2">
              <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium border bg-amber-100 text-amber-800 border-amber-300">
                downtime
              </span>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium border bg-purple-100 text-purple-800 border-purple-300">
                quality
              </span>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-semibold border bg-red-100 text-red-800 border-red-300">
                safety
              </span>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium border bg-slate-100 text-slate-800 border-slate-300">
                info
              </span>
            </div>
          </div>
          <div className="text-xs text-slate-500 font-mono">
            Active Shift: <strong className="text-slate-800">{selectedShiftKey}</strong>
          </div>
        </section>

        {activeTab === 'board' ? (
          <div className="space-y-6">
            {/* Shift Event Logging & Event Table Section */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              <div className="lg:col-span-5">
                <EventForm
                  shiftKey={selectedShiftKey}
                  onEventCreated={handleEventCreated}
                  onError={handleError}
                />
              </div>
              <div className="lg:col-span-7">
                <EventList
                  shiftKey={selectedShiftKey}
                  refreshKey={refreshKey}
                  onEventDeleted={handleEventDeleted}
                  onError={handleError}
                />
              </div>
            </div>

            {/* Handover Report Action Bar */}
            <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-slate-900">
                  Shift Handover Report Generation
                </h2>
                <p className="text-xs text-slate-500">
                  Synthesize logged operational events into structured executive summaries and open actions.
                </p>
              </div>
              <GenerateButton
                shiftKey={selectedShiftKey}
                eventCount={eventCount}
                hasExistingReport={Boolean(currentReport)}
                currentVersion={currentReport?.version}
                onReportGenerated={handleReportGenerated}
                onError={handleError}
              />
            </div>

            {/* Current Generated Report View */}
            <ReportView
              report={currentReport}
              shiftKey={selectedShiftKey}
              onRetry={() => setRefreshKey((k) => k + 1)}
            />
          </div>
        ) : (
          <div className="space-y-6">
            <ReportHistory shiftKey={selectedShiftKey} />
          </div>
        )}
      </main>

      {/* Admin Panel Modal */}
      <AdminPanel
        isOpen={isAdminOpen}
        onClose={() => setIsAdminOpen(false)}
      />

      {/* Global Error Toast Container */}
      <ToastContainer />

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-white py-4 px-6 text-center text-xs text-slate-500">
        Shift Handover Copilot &copy; 2026 &mdash; Built with Vite, React, and Tailwind CSS
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AppShell />
    </ToastProvider>
  );
}
