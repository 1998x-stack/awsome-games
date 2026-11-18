#!/usr/bin/env python3
"""One deterministic policy for project-level playable_status aggregation.

This is a *descriptive project summary*, not a license, gameplay verification,
or authorization to publish. build_site.py separately gates each mapping by
repo allowlist + entrypoint status + an actual vendored file.
"""
from __future__ import annotations

from collections.abc import Iterable

# Increasing leniency for restricting a particular mapping. A new observation
# must not weaken an older restriction without an explicit evidenced retraction.
RESTRICTIVE_STATUS_PRIORITY = (
    "sandbox_incompatible",
    "runtime_verification_failed",
    "runtime_requires_network",
    "runtime_third_party_beacon",
    "runtime_optional_sensor_denied",
    "runtime_input_not_attributable",
    "runtime_no_interaction",
    "runtime_driver_timeout",
    "runtime_needs_retest",
)
RUNTIME_REVIEWED_STATUSES = frozenset(RESTRICTIVE_STATUS_PRIORITY)
DECLARED_REVIEWED_STATUSES = frozenset(("not_browser_based", "requires_build"))

# Prefer an independently usable mapping to a broken *different* mirror.
# A project-level positive never authorizes another repository's artifact.
# Within unpublishable states prefer measured restrictions to untested guesses.
AGGREGATE_PRIORITY = (
    "smoke_test_passed",
    "entrypoint_found",
    *RESTRICTIVE_STATUS_PRIORITY,
    "entrypoint_detected_not_vendored",
    "missing_assets",
    "requires_build",
    "not_browser_based",
    "external_demo",
    "needs_review",
    "not_checked",
)


def aggregate_status(statuses: Iterable[str]) -> str:
    observed = {s for s in statuses if isinstance(s, str) and s}
    for status in AGGREGATE_PRIORITY:
        if status in observed:
            return status
    # Unknown statuses must not turn a project into a positive/servable claim.
    return "needs_review" if observed else "not_checked"


def update_project_aggregates(conn, project_ids: Iterable[str], stamp: str) -> set[str]:
    """Recompute each affected project from all of its repository mappings.

    Only update timestamps when the aggregate actually changes. Call within
    the caller's transaction, after all mapping changes are made.
    """
    touched = set()
    for project_id in sorted(set(project_ids)):
        mappings = conn.execute(
            "SELECT playable_status FROM project_repositories WHERE project_id=?",
            (project_id,)
        ).fetchall()
        if not mappings:
            continue  # External-demo-only projects have no repository mappings.
        aggregate = aggregate_status(r[0] for r in mappings)
        old = conn.execute(
            "SELECT playable_status FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if old is None or old[0] == aggregate:
            continue
        conn.execute(
            "UPDATE projects SET playable_status=?, updated_at=? WHERE id=?",
            (aggregate, stamp, project_id)
        )
        touched.add(project_id)
    return touched
