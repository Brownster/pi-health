# Compact Container Actions

Date: 2026-07-15  
Status: Approved for implementation

## Goal

Reduce repeated visual weight in the Containers table while keeping common operations fast,
clear, and accessible.

## Design

- Replace text-heavy row actions with a compact icon rail.
- Show only valid lifecycle actions for the current state:
  - Running: stop and restart.
  - Stopped or exited: start.
- Keep logs as a one-click icon action.
- Move the web UI link beside the container name and use an external-link icon.
- Place check update, update, and network test in a labelled overflow menu.
- Retain action colors, disabled states, pending indicators, accessible names, and tooltips.
- Use the same action model in the desktop table and responsive container cards.

## Verification

- Confirm lifecycle actions remain reachable on desktop, tablet, and phone.
- Confirm the overflow menu supports keyboard dismissal and closes after selection.
- Confirm update safeguards, logs, network diagnostics, and web links preserve their behavior.
- Confirm the page has no horizontal overflow at supported viewports.
