# Ops-Copilot AI Page Integration Plan

## 1. Objectives and Success Criteria
- Deliver a first-class "Ops-Copilot" experience inside the existing Pi-Health Flask + static Tailwind UI without breaking the current navigation, auth gate, or styling language.
- Surface the demo layout (chat, service health, quick actions, approval modal) as a dedicated page that consumes real backend data instead of hard-coded placeholders.
- Ensure the new page plays nicely with small screens, dark theme, and the Coraline-inspired visual style already used across `static/*.html`.
- Provide a maintainable path to evolve from mocked AI responses to live backend + MCP integration when ready.

## 2. Current-State Review
- Static assets live under `static/` with Tailwind CDN + handcrafted CSS. Navigation bar is duplicated across pages, and session auth relies on `sessionStorage.loggedIn` checks.
- Backend (`app.py`) exposes REST-ish JSON endpoints for system stats and container control, but nothing yet for AI interactions or approval flows.
- No bundler or component system; JavaScript is written inline per page. Modal + status badge patterns exist (e.g., `containers.html`) that we can reuse.

## 3. Target Experience Overview
- **Route & Navigation**: `/ops-copilot.html` added to the nav alongside Home/System Health/Containers/Edit.
- **Layout**: Two-column desktop layout with chat on the left and telemetry/actions on the right, collapsing into single column on <1024px viewports. Use Tailwind utility classes where possible; isolate any custom gradients in a scoped `<style>` block or separate CSS file.
- **Chat Panel**: Scrollable history, input textarea with enter-to-send, loading indicator, and approval CTA injection for fixes.
- **System Cards**: Service status list (using existing container data API), quick action shortcuts, live status bar (CPU, RAM, temp) across top.
- **Approval Modal**: Tailwind-based modal matching house style; triggered by "Apply Fix" button and able to send approval payload back to backend.

## 4. Incremental Delivery Plan
1. **Scaffold Page & Navigation**
   - Copy header/nav/footer scaffolding from `index.html` to a new `static/ops-copilot.html` file.
   - Add nav link to `/ops-copilot.html` across all existing static pages to keep UX consistent.
   - Add guard script to redirect to login if `sessionStorage.loggedIn` is missing.

2. **Translate Demo Layout to Tailwind**
   - Recreate the demo structure using Tailwind utility classes to avoid large inline `<style>` blocks.
   - Define a small custom CSS section (e.g., chat bubble gradients) inside the page or a new `static/css/ops-copilot.css` if needed.
   - Ensure responsive grid uses Tailwind (`grid grid-cols-1 xl:grid-cols-[2fr_1fr] gap-6`).

3. **Mock Data Wiring (Phase 1)**
   - Implement front-end module pattern (`const aiState = { ... }`) to render placeholder chat exchanges and service status.
   - Use existing endpoints:
     - `/api/system-stats` for CPU/memory/temp load bar.
     - `/api/containers` for service status list (map container names to friendly labels/icons similar to `index.html`).
   - For quick actions, wire buttons to send pre-filled prompts through the chat pipeline.

4. **Backend Prep (Phase 1)**
   - Add Flask endpoints to backstop the UI even with mocked AI:
     - `POST /api/ops-copilot/chat` → accept `message`, return structured reply (`{messages: [...], suggestion?: {...}}`). Initially return canned responses.
     - `POST /api/ops-copilot/approve` → accept `{action_id}` and respond with success placeholder.
   - Guard routes with same auth check used elsewhere (session token or future JWT).
   - Ensure responses include unique IDs so the UI can match pending approvals.

5. **Frontend → Backend Integration**
   - Replace hard-coded `setTimeout` logic with fetch calls to new endpoints.
   - Display `loading` state while awaiting responses; show approval button only when backend sets `requiresApproval`.
   - Modal should POST to `/api/ops-copilot/approve` and update chat/services view when successful.

6. **Accessibility & Polish**
   - Verify color contrast of gradients/badges meets WCAG AA (adjust colors if needed to align with Tailwind palette).
   - Ensure keyboard navigation works: focus trapping in modal, Enter-to-send, Esc to close modal.
   - Add ARIA labels for chat log and quick action buttons.

7. **Testing & Validation**
   - Manual tests: navigation between pages, chat interactions, modal open/close, mobile viewport checks.
   - Automated (optional future): Cypress/Playwright smoke to ensure page loads and nav works.
   - Backend unit tests covering new Flask endpoints with mocked responses.

8. **Future Enhancements (Beyond Demo Integration)**
   - Swap mocked endpoints with real MCP backend once tool adapters are ready.
   - Persist chat history per session via backend.
   - Hook approval actions to Docker/tool adapters and update service cards from real command outcomes.
   - Add notification banner when MCP is offline or rate-limited.

## 5. Open Questions / Dependencies
- Authentication model for API POSTs (reuse current cookie/session or introduce JWT?).
- Source of real-time service metrics (extend `/api/containers` or create dedicated telemetry endpoint?).
- Where to log approved actions within the Flask app (e.g., reuse planned audit trail path?).
- Need for socket/polling to push live updates vs. periodic fetch.

## 6. Definition of Done for Initial Page Drop
- `ops-copilot.html` renders demo UI styled to match Pi-Health theme with responsive layout.
- Page pulls real container + system stats and displays them in status bar/service list.
- Chat interactions round-trip through backend mock endpoints with approval modal functioning.
- Navigation across all pages includes link to Ops-Copilot.
- Basic smoke testing notes captured (manual checklist or README update).
