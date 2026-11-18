#!/usr/bin/env python3
"""Isolated, input-driven check that an artifact actually responds to a user.

A page that merely loads is `BROWSER_LOAD_CHECKED`. This probe additionally
injects synthetic pointer and keyboard input and requires the *rendered output*
to change as a result, then records the evidence (hashes, not prose).

What a pass proves: the artifact rendered, produced output while idle, and its
output changed after user input — i.e. something is listening and reacting.
What a pass does NOT prove: that the game is correct, complete, fun, or that the
author owns it. There is deliberately no stronger status here than
`INPUT_RESPONSIVE`.

Run it inside the disposable network-isolated container created by
`scripts/isolation/Dockerfile.smoke`; never on the host for untrusted code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from browser_smoke import FRAME_SANDBOX, clean_entry, install_network_policy, serve_static_root
from input_attribution import (INPUT_RESPONSIVE, NOT_ATTRIBUTABLE, NO_OBSERVABLE_RESPONSE,
                               input_attribution)

# The full verdict vocabulary. Kept next to the rule that produces it so a new
# status cannot be added to the rule and forgotten here.
STATUSES = (INPUT_RESPONSIVE, NO_OBSERVABLE_RESPONSE, NOT_ATTRIBUTABLE,
            "INCOMPLETE_OR_FAILED")
# Keys that almost any browser game uses for movement / action.
INPUT_KEYS = ("ArrowUp", "ArrowRight", "ArrowDown", "ArrowLeft", "Space",
              "KeyW", "KeyD", "KeyS", "KeyA", "Enter")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frame_fingerprint(page, iframe) -> dict:
    """Rendering-agnostic fingerprint: the rendered pixels of the whole iframe."""
    out = {"pixels": "", "pixel_error": ""}
    try:
        out["pixels"] = _digest(iframe.screenshot(timeout=15000))
    except Exception as exc:  # pragma: no cover - depends on rendering backend
        out["pixel_error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def frame_dom_census(child) -> str:
    try:
        payload = child.evaluate("""() => {
          const text = (document.body && document.body.innerText || '').slice(0, 20000);
          let nodes = 0; try { nodes = document.getElementsByTagName('*').length; } catch (e) {}
          return nodes + '|' + text.length + '|' + text;
        }""")
        return _digest(str(payload).encode())
    except Exception as exc:
        return "census-error:" + type(exc).__name__


def apply_input(page, child, box) -> list:
    """Real user gestures: pointer moves/clicks then keyboard presses."""
    actions = []
    try:
        cx, cy = box["width"] / 2, box["height"] / 2
        page.mouse.move(box["x"] + cx, box["y"] + cy)
        actions.append("move")
        for dx, dy in ((0, 0), (-60, 0), (60, 0), (0, 40)):
            page.mouse.click(box["x"] + cx + dx, box["y"] + min(max(cy + dy, 8), box["height"] - 8))
            actions.append(f"click{int(dx)},{int(dy)}")
        page.wait_for_timeout(250)
        for key in INPUT_KEYS:
            page.keyboard.down(key)
            page.wait_for_timeout(120)
            page.keyboard.up(key)
            actions.append(f"key:{key}")
    except Exception as exc:
        actions.append(f"input-error:{type(exc).__name__}")
    return actions


def probe(root: Path, entry: str, screenshot: Path | None = None,
          idle_ms: int = 900, settle_ms: int = 1500) -> dict:
    from playwright.sync_api import sync_playwright

    root = root.resolve()
    clean_entry(root, entry)
    host_html = ('<html><head><meta charset="utf-8"><title>Isolated gameplay host</title>'
                 '<style>html,body{margin:0;height:100%}iframe{width:100%;height:100%;border:0;display:block}</style>'
                 '</head><body><iframe title="third party game" sandbox="' + FRAME_SANDBOX
                 + '" referrerpolicy="no-referrer" src="/' + quote(entry, safe="/")
                 + '"></iframe></body></html>')
    server, thread, port = serve_static_root(root, "/__gameplay_host__", lambda query: host_html)

    result = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "entry": entry,
        "status": "NOT_RUN",
        "iframe_isolation": False,
        "frame_body_loaded": False,
        "console_errors": [],
        "blocked_requests": [],
        "blocked_websockets": [],
        "stubbed_cosmetic_requests": [],
        "failed_requests": [],
        "http_errors": [],
        "actions": [],
        "idle_output_changed": False,
        "input_changed_pixels": False,
        "input_changed_dom": False,
        "idle_dom_changed": False,
        "fingerprints": {},
        "screenshot": None,
        # This probe measures ONE thing: did rendered output change after synthetic
        # input. That is not gameplay verification, and an automated run must not
        # claim it, so gameplay_verified stays False and the measured fact is
        # reported separately as input_responsive.
        "gameplay_verified": False,
        "input_responsive": False,
        "evidence_scope": ("rendered output changed after synthetic pointer/keyboard input; "
                           "does not prove the game is correct, complete or author-owned"),
    }
    browser = None
    try:
        with sync_playwright() as p:
            launch = {"headless": True}
            chromium = os.environ.get("CHROMIUM_PATH", "").strip()
            if chromium:
                launch["executable_path"] = chromium
            browser = p.chromium.launch(**launch)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                      accept_downloads=False, service_workers="block",
                                      permissions=[], java_script_enabled=True,
                                      ignore_https_errors=False)
            install_network_policy(ctx, result, port)
            page = ctx.new_page()
            page.on("console", lambda m: result["console_errors"].append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda ex: result["console_errors"].append(str(ex)))
            page.on("requestfailed", lambda req: result["failed_requests"].append(req.url))
            page.on("response", lambda r: result["http_errors"].append({"url": r.url, "status": r.status})
                    if r.status >= 400 else None)

            page.goto(f"http://127.0.0.1:{port}/__gameplay_host__",
                      wait_until="domcontentloaded", timeout=30000)
            iframe = page.locator("iframe")
            iframe.wait_for(timeout=30000)
            page.wait_for_timeout(1200)

            child = next((f for f in page.frames if f != page.main_frame), None)
            if child is not None:
                try:
                    result["frame_body_loaded"] = child.locator("body").count() > 0
                except Exception as exc:
                    result["console_errors"].append("body probe: " + str(exc))
                try:
                    result["iframe_isolation"] = child.evaluate(
                        "() => {try{void parent.document.body;return false}catch(e){return true}}")
                except Exception as exc:
                    result["console_errors"].append("frame probe: " + str(exc))

            box = iframe.bounding_box() or {"x": 0, "y": 0, "width": 800, "height": 600}
            f1 = frame_fingerprint(page, iframe)
            dom1 = frame_dom_census(child) if child else ""
            page.wait_for_timeout(idle_ms)
            f2 = frame_fingerprint(page, iframe)
            dom2 = frame_dom_census(child) if child else ""
            result["idle_output_changed"] = bool(f1["pixels"] and f2["pixels"] and f1["pixels"] != f2["pixels"])

            result["actions"] = apply_input(page, child, box)
            page.wait_for_timeout(settle_ms)
            f3 = frame_fingerprint(page, iframe)
            dom3 = frame_dom_census(child) if child else ""
            result["input_changed_pixels"] = bool(f2["pixels"] and f3["pixels"] and f2["pixels"] != f3["pixels"])
            result["input_changed_dom"] = bool(dom2 and dom3 and dom2 != dom3)
            result["idle_dom_changed"] = bool(dom1 and dom2 and dom1 != dom2)
            result["fingerprints"] = {
                "initial_pixels": f1["pixels"], "idle_pixels": f2["pixels"], "after_input_pixels": f3["pixels"],
                "initial_dom": dom1, "idle_dom": dom2, "after_input_dom": dom3,
                "pixel_error": f1["pixel_error"] or f2["pixel_error"] or f3["pixel_error"],
            }

            if screenshot is not None:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot), full_page=False)
                result["screenshot"] = str(screenshot)
                result["screenshot_sha256"] = _digest(screenshot.read_bytes())

            load_ok = (result["frame_body_loaded"] and result["iframe_isolation"]
                       and not result["console_errors"] and not result["blocked_requests"]
                       and not result["blocked_websockets"] and not result["failed_requests"]
                       and not result["http_errors"])
            # Pixels changing after input is not by itself evidence of input response:
            # see scripts/input_attribution.py for why, and for the measured numbers
            # that forced the distinction.
            verdict = input_attribution(result)
            if not load_ok:
                result["status"] = "INCOMPLETE_OR_FAILED"
            else:
                result["status"] = verdict
                result["input_responsive"] = verdict == INPUT_RESPONSIVE
            ctx.close()
            browser.close()
            browser = None
    finally:
        if browser:
            browser.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--screenshot", type=Path)
    ap.add_argument("--idle-ms", type=int, default=900)
    ap.add_argument("--settle-ms", type=int, default=1500)
    args = ap.parse_args()
    info = probe(args.root, args.entry, args.screenshot, args.idle_ms, args.settle_ms)
    body = json.dumps(info, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(body + "\n", encoding="utf-8")
    print(body)
    if info["status"] != INPUT_RESPONSIVE:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
