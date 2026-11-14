# Design System & UI Guidelines — Shift Handover Copilot

## 1. UI Stack & Principles
- **Stack:** React + TypeScript + Vite, styled with **Tailwind CSS** and **shadcn/ui** component primitives.
- **Context:** Industrial plant environment. Interfaces must be high-contrast, clean, and legible under varying light and monitor conditions.
- **Security Rule:** Render all report and event notes strictly as text (React default escaping). **Never** use `dangerouslySetInnerHTML`.

---

## 2. Layout & Views
The application is desktop-first and structured around three primary views:

1. **Shift Board (`/`)**
   - **Header:** Shift selector dropdown/segmented control (`YYYY-MM-DD-{early|late|night}`).
   - **Event Logger Form:** Machine input, Category selector, Note textarea (max 2000 chars), Submit button.
   - **Event Table / Feed:** Chronological table of logged events with category badges and delete actions.
   - **Action Bar:** "Generate Handover" button (disabled if 0 events), with cold-start wakeup progress hint.
   - **Current Report Card:** Displays latest report sections (Summary, Open Actions, Safety Notes).
2. **Report History (`/reports`)**
   - Paginated/scrollable list of past generated shift handovers with version badges.
3. **Report Detail (`/reports/:id`)**
   - Read-only historical snapshot displaying exact version, model used, timestamp, and report content.

---

## 3. Visual Tokens & Components

### 3.1 Category Badges
| Category | Badge Color (Tailwind) | Use Case |
|---|---|---|
| `downtime` | Amber / Warning (`bg-amber-100 text-amber-800 border-amber-300`) | Machine stops, mechanical/electrical issues |
| `quality` | Purple (`bg-purple-100 text-purple-800 border-purple-300`) | Out-of-spec products, scrap, defects |
| `safety` | Red / Destructive (`bg-red-100 text-red-800 border-red-300 font-semibold`) | Near-misses, injuries, hazards |
| `info` | Slate / Neutral (`bg-slate-100 text-slate-800 border-slate-300`) | Shift changes, maintenance notes, observations |

### 3.2 Action Priorities
- **High:** Red badge / font bold (`text-red-700 bg-red-50`)
- **Medium:** Amber badge (`text-amber-700 bg-amber-50`)
- **Low:** Slate badge (`text-slate-600 bg-slate-50`)

### 3.3 Asynchronous States & Cold Starts
- **Cold Start Notification:** Display a persistent subtle alert when requests exceed 3s:
  > *"Waking up the database — the first request after an idle period may take up to 20 s."*
- **Error Toasts:** Display RFC 9457 problem details toast containing the error message and clickable/copyable `trace_id`.

---

## 4. State & Data Layer
- **Client State & Server Cache:** Managed via **TanStack Query** (`@tanstack/react-query`).
- **Services Layer:** Centralized API client functions with toggled mock (`VITE_API_MODE=mock`) and real HTTP backend.
