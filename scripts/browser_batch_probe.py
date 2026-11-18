#!/usr/bin/env python3
"""Run isolated load/interaction checks for MANY entries, ONE bounded subprocess each.

Two bad third-party pages (an infinite loop, a pointer-lock prompt) can stall a
single-browser batch forever: a synchronous `evaluate` against a page that never
yields cannot be interrupted, so a watchdog inside the same process is useless.
Each entry therefore runs in its own process group that is hard-killed on
timeout, and the timeout is recorded honestly as TIMEOUT_ABORTED instead of
silently dropping the artifact.

Isolation is unchanged and installed BEFORE the first navigation: loopback-only
requests, WebSocket denied, web fonts stubbed locally, sandboxed iframe without
`allow-same-origin`. Run through
`scripts/isolation/run_isolated_smoke.sh --mode batch` so the OS-level network
namespace still applies.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from browser_smoke import FRAME_SANDBOX, clean_entry, install_network_policy, serve_static_root
from browser_gameplay_probe import apply_input, frame_dom_census, frame_fingerprint
from input_attribution import (INPUT_RESPONSIVE, NOT_ATTRIBUTABLE, NO_OBSERVABLE_RESPONSE,
                               input_attribution)

HOST_PATH = "/__batch_host__"
SUB_STATUS = ("BROWSER_LOAD_CHECKED", INPUT_RESPONSIVE, NOT_ATTRIBUTABLE,
              NO_OBSERVABLE_RESPONSE, "INCOMPLETE_OR_FAILED", "TIMEOUT_ABORTED")


def build_host(query: dict) -> str:
    entry = (query.get("entry") or [""])[0]
    if not entry:
        return "<html><body>missing entry</body></html>"
    return ('<html><head><meta charset="utf-8"><title>Isolated batch host</title>'
            '<style>html,body{margin:0;height:100%}iframe{width:100%;height:100%;border:0;display:block}</style>'
            '</head><body><iframe title="third party" sandbox="' + FRAME_SANDBOX
            + '" referrerpolicy="no-referrer" src="/' + quote(entry, safe="/")
            + '"></iframe></body></html>')


def reap_orphan_browsers() -> int:
    """Kill browsers left behind by a hard-killed entry.

    Entries run strictly one at a time, so any surviving renderer belongs to the
    entry we just abandoned and would otherwise accumulate until the container's
    pid or memory limit is hit. Linux-only; a no-op elsewhere.
    """
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return 0
    killed = 0
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "headless_shell" in cmdline or "chrome_crashpad" in cmdline:
            try:
                os.kill(int(entry.name), signal.SIGKILL)
                killed += 1
            except OSError:
                pass
    return killed


def blank_result(entry: str, mode: str) -> dict:
    return {"tested_at": datetime.now(timezone.utc).isoformat(), "entry": entry, "mode": mode,
            "status": "NOT_RUN", "iframe_isolation": False, "frame_body_loaded": False,
            "console_errors": [], "blocked_requests": [], "blocked_websockets": [],
            "stubbed_cosmetic_requests": [], "failed_requests": [], "http_errors": [],
            "actions": [], "idle_output_changed": False, "input_changed_pixels": False,
            "input_changed_dom": False, "idle_dom_changed": False,
            "gameplay_verified": False, "input_responsive": False}


def measure(page, iframe, child, mode: str, idle_ms: int, settle_ms: int) -> dict:
    out = {"actions": [], "idle_output_changed": False, "input_changed_pixels": False,
           "input_changed_dom": False, "idle_dom_changed": False}
    box = iframe.bounding_box() or {"x": 0, "y": 0, "width": 800, "height": 600}
    f1 = frame_fingerprint(page, iframe)
    dom1 = frame_dom_census(child) if child else ""
    page.wait_for_timeout(idle_ms)
    f2 = frame_fingerprint(page, iframe)
    dom2 = frame_dom_census(child) if child else ""
    out["idle_output_changed"] = bool(f1["pixels"] and f2["pixels"] and f1["pixels"] != f2["pixels"])
    if mode == "gameplay":
        out["actions"] = apply_input(page, child, box)
        page.wait_for_timeout(settle_ms)
    f3 = frame_fingerprint(page, iframe)
    dom3 = frame_dom_census(child) if child else ""
    out["input_changed_pixels"] = bool(f2["pixels"] and f3["pixels"] and f2["pixels"] != f3["pixels"])
    out["input_changed_dom"] = bool(dom2 and dom3 and dom2 != dom3)
    out["idle_dom_changed"] = bool(dom1 and dom2 and dom1 != dom2)
    out["fingerprints"] = {"initial_pixels": f1["pixels"], "idle_pixels": f2["pixels"],
                           "after_input_pixels": f3["pixels"], "initial_dom": dom1,
                           "idle_dom": dom2, "after_input_dom": dom3,
                           "pixel_error": f1["pixel_error"] or f2["pixel_error"] or f3["pixel_error"]}
    return out


def run_single(root: Path, item: dict, idle_ms: int, settle_ms: int) -> dict:
    """One entry, one browser, one process. Never reuses state across artifacts."""
    from playwright.sync_api import sync_playwright

    root = root.resolve()
    entry = item["entry"]
    mode = item.get("mode", "load")
    clean_entry(root, entry)
    result = blank_result(entry, mode)
    server, thread, port = serve_static_root(root, HOST_PATH, build_host)
    base = f"http://127.0.0.1:{port}"
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
            ctx.set_default_timeout(15000)
            # Isolation first: nothing may be requested before this.
            install_network_policy(ctx, result, port)
            page = ctx.new_page()
            page.on("console", lambda m: result["console_errors"].append(m.text)
                    if m.type == "error" else None)
            page.on("pageerror", lambda ex: result["console_errors"].append(str(ex)))
            page.on("requestfailed", lambda req: result["failed_requests"].append(req.url))
            page.on("response", lambda r: result["http_errors"].append(
                {"url": r.url, "status": r.status}) if r.status >= 400 else None)
            page.goto(f"{base}{HOST_PATH}?entry={quote(entry, safe='')}",
                      wait_until="domcontentloaded", timeout=30000)
            iframe = page.locator("iframe")
            iframe.wait_for(timeout=30000)
            page.wait_for_timeout(1200)
            child = next((f for f in page.frames if f != page.main_frame), None)
            if child is not None:
                try:
                    result["frame_body_loaded"] = child.locator("body").count() > 0
                except Exception as exc:
                    result["console_errors"].append("body probe: " + str(exc)[:200])
                try:
                    result["iframe_isolation"] = child.evaluate(
                        "() => {try{void parent.document.body;return false}catch(e){return true}}")
                except Exception as exc:
                    result["console_errors"].append("frame probe: " + str(exc)[:200])
            result.update(measure(page, iframe, child, mode, idle_ms, settle_ms))
            load_ok = (result["frame_body_loaded"] and result["iframe_isolation"]
                       and not result["console_errors"] and not result["blocked_requests"]
                       and not result["blocked_websockets"] and not result["failed_requests"]
                       and not result["http_errors"])
            verdict = input_attribution(result)
            if not load_ok:
                result["status"] = "INCOMPLETE_OR_FAILED"
            elif mode == "gameplay":
                # Same rule as the standalone gameplay probe: a page that repaints on
                # its own is NOT_ATTRIBUTABLE, not a success.
                result["status"] = verdict
                result["input_responsive"] = verdict == INPUT_RESPONSIVE
            else:
                result["status"] = "BROWSER_LOAD_CHECKED"
            ctx.close()
    except Exception as exc:
        result["status"] = "INCOMPLETE_OR_FAILED"
        result["console_errors"].append(f"driver error: {type(exc).__name__}: {exc}"[:300])
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    return result


def timeout_result(entry: str, mode: str, seconds: int) -> dict:
    result = blank_result(entry, mode)
    result["status"] = "TIMEOUT_ABORTED"
    result["console_errors"] = [f"hard timeout after {seconds}s; the page blocked the driver "
                                "and the process group was killed"]
    return result


def run_batch(root: Path, items: list[dict], out: Path, idle_ms: int, settle_ms: int,
              per_entry_timeout: int) -> dict:
    root = root.resolve()
    for item in items:  # fail early on any unsafe path, before spawning anything
        clean_entry(root, item["entry"])
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for item in items:
        key = item["key"].replace("/", "__")
        target = out / f"{key}.json"
        cmd = [sys.executable, str(Path(__file__).resolve()), "--single", "--root", str(root),
               "--out", str(out), "--item", json.dumps(item, ensure_ascii=False),
               "--idle-ms", str(idle_ms), "--settle-ms", str(settle_ms)]
        status = "TIMEOUT_ABORTED"
        timed_out = False
        # Redirect to a file, never a pipe: Chromium's sandboxed children call
        # setsid and can outlive the group kill while still holding an inherited
        # pipe, which would block communicate() forever and stall the batch.
        log_path = out / (key + ".log")
        try:
            with log_path.open("w", encoding="utf-8") as log_fh:
                # `timeout -s KILL` is the supervisor: a page that blocks the
                # driver cannot be interrupted from Python, so an external tool
                # must own the deadline.
                supervised = ["timeout", "-s", "KILL", str(per_entry_timeout)] + cmd
                proc = subprocess.Popen(supervised, stdout=log_fh, stderr=subprocess.STDOUT,
                                        start_new_session=True)
                try:
                    proc.wait(timeout=per_entry_timeout + 30)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        try:
                            proc.kill()
                        except OSError:
                            pass
                    try:
                        proc.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        pass
                if proc.returncode in (-signal.SIGKILL, 137):
                    timed_out = True
            stderr = log_path.read_text(encoding="utf-8", errors="replace")
            reap_orphan_browsers()
            if timed_out:
                target.write_text(json.dumps(timeout_result(item["entry"], item.get("mode", "load"),
                                                            per_entry_timeout),
                                             ensure_ascii=False, indent=2), encoding="utf-8")
            elif proc.returncode != 0 and not target.is_file():
                status = "INCOMPLETE_OR_FAILED"
                target.write_text(json.dumps(
                    {**blank_result(item["entry"], item.get("mode", "load")),
                     "status": status,
                     "console_errors": [f"runner exited {proc.returncode}: "
                                        f"{(stderr or '')[-300:]}"]},
                    ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            status = "INCOMPLETE_OR_FAILED"
            target.write_text(json.dumps(
                {**blank_result(item["entry"], item.get("mode", "load")), "status": status,
                 "console_errors": [f"runner failed: {type(exc).__name__}: {exc}"[:300]]},
                ensure_ascii=False, indent=2), encoding="utf-8")
        report = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else \
            timeout_result(item["entry"], item.get("mode", "load"), per_entry_timeout)
        summaries.append({
            "key": item["key"], "entry": item["entry"], "mode": item.get("mode", "load"),
            "status": report["status"],
            "gameplay_verified": bool(report.get("gameplay_verified")),
            "input_responsive": bool(report.get("input_responsive")),
            "idle_output_changed": bool(report.get("idle_output_changed")),
            "console_errors": len(report.get("console_errors", [])),
            "blocked": len(report.get("blocked_requests", [])),
            "stubbed_cosmetic": len(report.get("stubbed_cosmetic_requests", [])),
        })
    return {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "total": len(summaries), "per_entry_timeout_s": per_entry_timeout,
            "results": summaries}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, help="batch mode: JSON list of {key,entry,mode}")
    ap.add_argument("--item", help="single mode: JSON object for one entry")
    ap.add_argument("--single", action="store_true", help="internal: run exactly one entry")
    ap.add_argument("--emit-timeout", action="store_true",
                    help="internal: record an honest TIMEOUT_ABORTED for one entry")
    ap.add_argument("--idle-ms", type=int, default=900)
    ap.add_argument("--settle-ms", type=int, default=1500)
    ap.add_argument("--per-entry-timeout", type=int, default=90)
    args = ap.parse_args()
    if args.single:
        if not args.item:
            ap.error("--single requires --item")
        item = json.loads(args.item)
        report = run_single(args.root, item, args.idle_ms, args.settle_ms)
        args.out.mkdir(parents=True, exist_ok=True)
        # The parent reads this file; printing alone is not enough.
        (args.out / (item['key'].replace('/', '__') + '.json')).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return
    if args.emit_timeout:
        if not args.item:
            ap.error("--emit-timeout requires --item")
        item = json.loads(args.item)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / (item["key"].replace("/", "__") + ".json")).write_text(
            json.dumps(timeout_result(item["entry"], item.get("mode", "load"),
                                      args.per_entry_timeout), ensure_ascii=False, indent=2),
            encoding="utf-8")
        return
    if not args.manifest:
        ap.error("batch mode requires --manifest")
    items = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = run_batch(args.root, items, args.out, args.idle_ms, args.settle_ms,
                       args.per_entry_timeout)
    (args.out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    for row in report["results"]:
        print(f"{row['status']:22} {row['mode']:9} err={row['console_errors']} "
              f"blk={row['blocked']} stub={row['stubbed_cosmetic']} {row['entry']}")
    counts = {}
    for row in report["results"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"\nTOTAL {report['total']} | " +
          " | ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
