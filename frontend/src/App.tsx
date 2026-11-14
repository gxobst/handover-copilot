export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col">
      <header className="bg-slate-900 text-white border-b border-slate-800 px-6 py-4 shadow-sm">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <span className="inline-block w-3 h-3 rounded-full bg-emerald-500 animate-pulse" aria-hidden="true" />
            <h1 className="text-xl font-bold tracking-tight">Shift Handover Copilot</h1>
          </div>
          <span className="text-xs uppercase tracking-wider text-slate-400 font-medium px-2.5 py-1 rounded border border-slate-700 bg-slate-800">
            Industrial Plant Edition
          </span>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        <section className="bg-white rounded-lg border border-slate-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900 mb-2">Shift Board Overview</h2>
          <p className="text-sm text-slate-600 mb-6">
            Production-ready frontend workspace initialized with Vite, React, TypeScript, Tailwind CSS, and Vitest.
          </p>

          <div className="border-t border-slate-200 pt-4">
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
              Design System Category Badges
            </h3>
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
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white py-4 px-6 text-center text-xs text-slate-500">
        Shift Handover Copilot &copy; 2026 &mdash; Built with Vite, React, and Tailwind CSS
      </footer>
    </div>
  )
}
