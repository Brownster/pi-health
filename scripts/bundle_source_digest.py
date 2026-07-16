#!/usr/bin/env python3
"""Digest of the v2 frontend build inputs, used to detect a stale committed bundle.

`static/v2/` is committed and is the source of truth for devices without npm (they can't
rebuild — see the helper's build step). Nothing otherwise guarantees the committed bundle
matches the source, so editing `frontend/src` without running `build:publish` ships stale UI.

This computes a stable digest over the build inputs and stores it in `static/v2/.bundle-source`
at publish time. A gate test recomputes it and fails if it drifts; the self-update helper uses
it to decide whether to rebuild (npm present) or warn (npm absent).

Usage:
  bundle_source_digest.py            # print the current source digest
  bundle_source_digest.py --write    # compute and write the marker
  bundle_source_digest.py --check    # exit 0 if marker matches source, 1 otherwise
"""

from __future__ import annotations

import hashlib
import os
import sys

# Inputs that determine the built bundle. Kept deliberately narrow to what a developer edits;
# broaden if a config change ever ships without a corresponding src change.
SOURCE_PARTS = ("frontend/src", "frontend/index.html")
MARKER_PATH = "static/v2/.bundle-source"


def _iter_files(repo_root: str):
    for part in SOURCE_PARTS:
        path = os.path.join(repo_root, part)
        if os.path.isfile(path):
            yield part, path
        elif os.path.isdir(path):
            for root, dirs, names in os.walk(path):
                dirs.sort()
                for name in sorted(names):
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, repo_root).replace(os.sep, "/")
                    yield rel, full


def compute_digest(repo_root: str) -> str:
    digest = hashlib.sha256()
    for rel, full in sorted(_iter_files(repo_root)):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        with open(full, "rb") as handle:
            digest.update(handle.read())
        digest.update(b"\0")
    return digest.hexdigest()


def read_marker(repo_root: str) -> str | None:
    try:
        with open(os.path.join(repo_root, MARKER_PATH), encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv: list[str]) -> int:
    repo_root = _repo_root()
    digest = compute_digest(repo_root)
    if "--write" in argv:
        marker = os.path.join(repo_root, MARKER_PATH)
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write(digest + "\n")
        print(f"wrote {MARKER_PATH} = {digest}")
        return 0
    if "--check" in argv:
        marker = read_marker(repo_root)
        if marker == digest:
            print("bundle is fresh")
            return 0
        print(f"bundle is STALE: marker={marker} source={digest}", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
