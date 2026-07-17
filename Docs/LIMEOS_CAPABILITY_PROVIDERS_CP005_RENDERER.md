# LimeOS Capability Providers CP-005 Generic Renderer

Date: 2026-07-17

Status: Implemented

Scope: CP-005 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Foundation

The generic renderer is a LimeOS-owned React layer under
`frontend/src/components/capabilities/`. It accepts the versioned CP-001 setup, status,
and action contracts. Providers supply data only; they cannot supply JavaScript, HTML,
CSS, remote assets, React components, or arbitrary commands.

The foundation contains:

- `GenericSetupForm` for flat schema fields, sections, typed values, and field errors
- `CapabilityStatusPanel` for lifecycle health, summary items, metrics, issues, and activity
- `CapabilityActions` for declared availability, typed parameters, confirmation, and progress
- `GenericCapabilityRenderer` to compose the three tools on a capability-owned page
- Pure renderer helpers for defaults, validation, choices, metrics, and event reduction

CP-005 does not mount a new page or replace Plugins and Pools. CP-013 and CP-015 will
connect the renderer to the capability domain pages.

## Rendering Rules

- Setup values remain a flat map, including dotted field keys.
- Sections group fields visually without nesting data or cards.
- Boolean fields use checkboxes; selects preserve string, number, and boolean values.
- Secret-reference fields contain reference identifiers only and disable autocomplete.
- Provider regex patterns are not executed in the browser. The backend remains the
  authority and returns stable field-scoped validation errors.
- Status `details` is reserved for tailored renderers and is never shown as raw JSON.
- Metrics are normalized only when they have a valid numeric range.
- Mutation and destructive actions always display provider-declared confirmation copy.
- Unknown actions cannot be introduced through the renderer; the page supplies a fixed
  executor for the declared catalog.

## Progress Bounds

The action reducer accepts one operation ID and strictly increasing sequence numbers.
It ignores duplicate, stale, and foreign events. Output is limited to 200 lines, 2,000
characters per event, and 64 KiB in the rendered console. The renderer does not display
arbitrary action result objects.

## Verification

Pure renderer behavior is covered by Node's built-in test runner through
`npm --prefix frontend run test:capabilities`. The normal TypeScript and Vite build
compile every renderer component. The committed `static/v2` bundle remains the target-Pi
delivery artifact.
