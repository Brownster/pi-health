# Fork and Branch Workflow

This project is currently at:

- Local branch: `main`
- Remote tracking: `origin/main`
- Status: local `main` is **ahead by 1 commit** (`4da0f40`) over `origin/main` (`d93caa3`)

## Goals

1. Keep a clean `main` aligned with upstream.
2. Do feature work on short-lived branches.
3. Push work to your fork and open PRs back to upstream.

## One-time remote layout

If `origin` points to your fork already, keep it and add upstream:

```bash
git remote add upstream https://github.com/<UPSTREAM_OWNER>/pi-health.git
git fetch upstream --prune
```

If `origin` points to upstream, create a fork and set remotes:

```bash
gh auth login -h github.com
gh repo fork <UPSTREAM_OWNER>/pi-health --clone=false --remote=true
git remote rename origin upstream
git remote add origin git@github.com:<YOUR_USER>/pi-health.git
git fetch --all --prune
```

## Sync procedure (run before each feature)

```bash
git checkout main
git fetch upstream --prune
git rebase upstream/main
git push origin main
```

If you intentionally keep local-only commits on `main`, move them to a feature branch first:

```bash
git checkout -b feat/<topic>
git checkout main
git reset --hard upstream/main
git push --force-with-lease origin main
```

## Branch and PR procedure

```bash
git checkout -b feat/ui-<page-or-scope>
# make changes
git add -A
git commit -m "feat(ui): migrate <page> to new component system"
git push -u origin feat/ui-<page-or-scope>
gh pr create --base main --head feat/ui-<page-or-scope> --fill
```

## Branch naming

- `feat/ui-shell-layout`
- `feat/ui-system-page`
- `feat/ui-containers-page`
- `refactor/ui-data-layer`
- `chore/ui-tooling`

## Guardrails

- Never develop directly on `main`.
- Keep each UI PR focused on one page or one shared UI concern.
- Rebase feature branches on `main` before opening/updating a PR.
- Require smoke tests to pass before merge.
