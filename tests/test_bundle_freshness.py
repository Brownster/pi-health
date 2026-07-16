"""Gate: the committed v2 bundle must match the frontend source.

`static/v2/` is committed and served verbatim on devices without npm (they can't rebuild), so
a stale committed bundle silently ships old UI. This fails the moment `frontend/src` changes
without a corresponding `npm --prefix frontend run build:publish`, which regenerates both the
bundle and its `.bundle-source` digest.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from bundle_source_digest import compute_digest, read_marker  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_committed_bundle_matches_frontend_source():
    marker = read_marker(_REPO_ROOT)
    assert marker is not None, (
        "static/v2/.bundle-source is missing — run "
        "`npm --prefix frontend run build:publish` and commit the result."
    )
    assert marker == compute_digest(_REPO_ROOT), (
        "The committed static/v2 bundle is stale relative to frontend/src. "
        "Run `npm --prefix frontend run build:publish` and commit static/v2."
    )
