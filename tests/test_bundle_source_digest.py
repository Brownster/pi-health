"""Unit tests for the frontend bundle source-digest tool."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from bundle_source_digest import compute_digest, read_marker  # noqa: E402


def _make_repo(tmp_path, tsx="export const A = 1;\n"):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "app.tsx").write_text(tsx)
    (tmp_path / "frontend" / "index.html").write_text("<!doctype html>")
    return str(tmp_path)


def test_digest_is_stable_for_identical_trees(tmp_path):
    root = _make_repo(tmp_path)
    assert compute_digest(root) == compute_digest(root)


def test_digest_changes_when_a_source_file_changes(tmp_path):
    root = _make_repo(tmp_path)
    before = compute_digest(root)
    (tmp_path / "frontend" / "src" / "app.tsx").write_text("export const A = 2;\n")
    assert compute_digest(root) != before


def test_digest_changes_when_a_source_file_is_added(tmp_path):
    root = _make_repo(tmp_path)
    before = compute_digest(root)
    (tmp_path / "frontend" / "src" / "b.tsx").write_text("export const B = 1;\n")
    assert compute_digest(root) != before


def test_read_marker_returns_none_when_absent(tmp_path):
    assert read_marker(str(tmp_path)) is None


def test_read_marker_roundtrips(tmp_path):
    root = _make_repo(tmp_path)
    marker = tmp_path / "static" / "v2" / ".bundle-source"
    marker.parent.mkdir(parents=True)
    marker.write_text(compute_digest(root) + "\n")
    assert read_marker(root) == compute_digest(root)
