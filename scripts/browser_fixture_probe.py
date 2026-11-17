#!/usr/bin/env python3
"""Run a controlled self-authored mini-game in an opaque-origin Chromium iframe.

This tests the sandbox and click interaction, NOT any third-party Fable game.
Runs without HTTP, useful when loopback navigation is disallowed.
Optional dependency: playwright + locally available Chromium.
"""
from __future__ import annotations
import argparse
import json
from html import escape
from pathlib import Path

FIXTURE = """<!doctype html><html lang="en"><body>
<h1>Fixture game</h1>
<button id="move" type="button">Move <span id="steps">0</span></button>
<script>
window.steps=0;
document.querySelector('#move').addEventListener('click',()=>{
  document.querySelector('#steps').textContent=String(++window.steps);
});
try{parent.document.body.dataset.escape="bad";window.parentAccess="unsafe"}
catch(error){window.parentAccess="blocked"}
</script></body></html>"""

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium",help="Explicit Chromium executable path, if Playwright has no managed browser")
    parser.add_argument("--screenshot",type=Path)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    from playwright.sync_api import sync_playwright
    report={"mode":"CONTROLLED_FIXTURE_ONLY","status":"NOT_RUN","gameplay_interaction":"NOT_RUN",
            "parent_document_access":"NOT_RUN","network_policy":"ALL_REQUESTS_BLOCKED",
            "third_party_games_verified":0}
    with sync_playwright() as p:
        opt={"headless":True}
        if args.chromium:opt["executable_path"]=args.chromium
        browser=p.chromium.launch(**opt)
        context=browser.new_context(permissions=[],accept_downloads=False,service_workers="block")
        context.route("**/*",lambda route:route.abort())
        page=context.new_page()
        html=('<main><h2>Parent research catalog</h2><iframe title="isolated" '
              'width="760" height="270" sandbox="allow-scripts allow-forms allow-pointer-lock allow-modals" '
              'srcdoc="'+escape(FIXTURE,quote=True)+'"></iframe></main>')
        page.set_content(html)
        frame=page.frame_locator("iframe")
        frame.locator("#move").click()
        frame.locator("#move").click()
        report["gameplay_interaction"]="PASS" if frame.locator("#steps").inner_text()=="2" else "FAIL"
        report["parent_document_access"]="BLOCKED" if frame.locator("body").evaluate(
            "() => window.parentAccess")=="blocked" else "UNSAFE"
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(args.screenshot),full_page=True)
            report["screenshot"]=str(args.screenshot)
        report["status"]="PASS" if report["gameplay_interaction"]=="PASS" and report["parent_document_access"]=="BLOCKED" else "FAIL"
        context.close()
        browser.close()
    result=json.dumps(report,ensure_ascii=False,indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(result+"\n",encoding="utf-8")
    print(result)
    if report["status"]!="PASS":raise SystemExit(1)

if __name__=="__main__":
    main()
