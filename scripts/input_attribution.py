#!/usr/bin/env python3
"""What a change seen after synthetic input actually proves.

A difference observed after input is only evidence that a page *responds to input*
when the same channel was stable beforehand. A page that repaints on its own — a
canvas animation, a clock, a shader, a particle field, a video — produces a pixel
difference whether or not anything was injected, so such a difference says nothing
about input. Measured against 2026-11-17 survey data this mattered a lot: 10 of 11
entries whose pixels changed after input were already changing during the idle
baseline, and in 7 of them the DOM census was byte-identical from load to finish.

The DOM channel is treated the same way: a DOM difference counts only when the DOM
census was unchanged across the idle window.

This module is deliberately dependency-free. The browser probes need Playwright and
the offline aggregator must not, so a single implementation lives here and all three
call it — the rule must not be allowed to drift between measurement and reporting.
"""
from __future__ import annotations

INPUT_RESPONSIVE = "INPUT_RESPONSIVE"
NOT_ATTRIBUTABLE = "INPUT_RESPONSE_NOT_ATTRIBUTABLE"
NO_OBSERVABLE_RESPONSE = "NO_OBSERVABLE_RESPONSE"

NOTE = ("A difference after synthetic input is attributed to input only when the same "
        "channel was stable beforehand. A page that repaints on its own cannot be "
        "distinguished from one that reacts to input by pixels alone, so it is recorded "
        "as INPUT_RESPONSE_NOT_ATTRIBUTABLE rather than as a success.")


def input_attribution(result: dict) -> str:
    """Classify one measurement. Reads only recorded raw evidence, so it can be
    re-applied offline to reports captured before this rule existed."""
    changed_dom = bool(result.get("input_changed_dom"))
    changed_pixels = bool(result.get("input_changed_pixels"))
    idle_pixels = bool(result.get("idle_output_changed"))
    idle_dom = bool(result.get("idle_dom_changed"))
    if (changed_dom and not idle_dom) or (changed_pixels and not idle_pixels):
        return INPUT_RESPONSIVE
    if changed_dom or changed_pixels or idle_pixels or idle_dom:
        return NOT_ATTRIBUTABLE
    return NO_OBSERVABLE_RESPONSE


def is_positive(status: str) -> bool:
    """The strongest claim an automated run is allowed to make."""
    return status == INPUT_RESPONSIVE
