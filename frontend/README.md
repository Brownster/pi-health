# Pi-Health Frontend v2 Foundation

Phase 1 foundation workspace for the React-based `/v2` UI.

## Commands

```bash
npm install
npm run dev
npm run build
npm run build:publish
```

## Build Artifact Contract

1. `npm run build` emits production assets to `frontend/dist/`.
2. App base path is fixed to `/v2/` in `vite.config.ts`.
3. `npm run build:publish` copies `frontend/dist/*` into `static/v2/` for Flask serving.
4. Flask integration and runtime mode switching are implemented in PH1-003 and PH1-004.

## Notes

1. Tailwind 4 is configured via `@tailwindcss/vite`.
2. `components.json` and `@/*` aliases are included for shadcn-compatible component generation.
3. Default theme mode is `dark`, with `light|dark|system` toggle support.
