#!/usr/bin/env python3
"""Ephemeral local-only Chromium smoke test for an already-reviewed HTML artifact.

No third-party install/build scripts. External network requests are aborted.
This is a browser-load check, NOT proof that a game is playable or author-owned.
Run inside a disposable container/VM for untrusted artifacts.
"""
from __future__ import annotations
import argparse
import json
import os
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, quote, unquote

FRAME_SANDBOX = "allow-scripts allow-pointer-lock allow-forms allow-modals"

# Web fonts and favicons are styling-only: a page can be meaningfully load-checked
# without them. They are satisfied with a local empty response so no external
# egress happens, and they are recorded separately instead of failing the run.
# Everything else (scripts, fetch/XHR, media, wasm, WebSocket) stays functional
# and fails closed.
COSMETIC_HOSTS = {
    "fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net",
    "fonts.bunny.net", "cdnjs.cloudflare.com/cosmetic-placeholder",
}
COSMETIC_STUB_CSS = "/* web font stubbed locally by the isolation policy */\n"


def is_cosmetic_request(url: str) -> bool:
    """True only for non-functional styling requests (web fonts, favicons)."""
    try:
        parsed = urlparse(url or "")
    except (ValueError, TypeError):
        return False
    host = (parsed.hostname or "").lower()
    if host in COSMETIC_HOSTS:
        return True
    return parsed.path.lower().endswith(("/favicon.ico", "apple-touch-icon.png"))


def install_network_policy(context, result: dict, allowed_port: int) -> None:
    """Deny every off-loopback request while keeping cosmetic ones non-fatal.

    """
    def secure_route(route):
        parsed = urlparse(route.request.url)
        if (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
                and parsed.port == allowed_port):
            return route.continue_()
        if is_cosmetic_request(route.request.url):
            result.setdefault("stubbed_cosmetic_requests", []).append(route.request.url)
            if parsed.path.lower().endswith(".ico"):
                return route.fulfill(status=204, body="")
            return route.fulfill(status=200, content_type="text/css", body=COSMETIC_STUB_CSS)
        result["blocked_requests"].append(route.request.url)
        return route.abort()

    context.route("**/*", secure_route)
    # HTTP request interception does not intercept WebSocket handshakes.
    # Fail closed on old Playwright rather than silently allowing egress.
    if not hasattr(context, "route_web_socket"):
        raise RuntimeError("Playwright >= 1.48 is required for WebSocket isolation")

    def close_websocket(ws):
        result["blocked_websockets"].append(ws.url)
        ws.close()

    context.route_web_socket("**/*", close_websocket)

def clean_entry(root: Path, entry: str) -> Path:
    if not entry or entry.startswith("/") or "\\" in entry or "?" in entry or "#" in entry:
        raise ValueError("entry must be a repository-relative HTML path")
    if any(x in entry for x in ('<','>','"',"'",'&','%')) or any(ord(c)<32 for c in entry):
        raise ValueError("unsafe entry characters")
    parts=Path(entry).parts
    if any(x in (".","..","") for x in parts) or not entry.lower().endswith((".htm",".html")):
        raise ValueError("unsafe entry path")
    full=(root/entry).resolve()
    if not full.is_relative_to(root.resolve()) or not full.is_file():
        raise ValueError("entry must exist inside the selected local root")
    return full

def smoke(root: Path, entry: str, screenshot: Path | None=None, timeout_ms: int=15000) -> dict:
    """Requires optional pip install playwright; caller must provide safe container/VM."""
    from playwright.sync_api import sync_playwright
    root=root.resolve()
    clean_entry(root,entry)
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(root),**kwargs)
        def translate_path(self,path):
            target=Path(super().translate_path(path)).resolve()
            if not target.is_relative_to(root):return str(root/'__denied__')
            return str(target)
        def do_GET(self):
            if self.path.split("?",1)[0]=="/__isolated_smoke_host__":
                payload=('<html><head><meta charset="utf-8"><title>Isolated test host</title></head>'
                         '<body><h1>Smoke test</h1><iframe title="third party" sandbox="'
                         +FRAME_SANDBOX+'" referrerpolicy="no-referrer" src="/'+quote(entry,safe='/')+'"></iframe></body></html>').encode()
                self.send_response(200);self.send_header("Content-Type","text/html;charset=utf-8")
                self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload)
            else:super().do_GET()
        def log_message(self,*args):
            return
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    port=server.server_address[1]
    result={"tested_at":datetime.now(timezone.utc).isoformat(),"entry":entry,"status":"NOT_RUN",
            "iframe_isolation":False,"frame_body_loaded":False,"console_errors":[],
            "blocked_requests":[],"blocked_websockets":[],"stubbed_cosmetic_requests":[],
            "failed_requests":[],"http_errors":[],"screenshot":None,
            "gameplay_verified":False,"network_policy":"browser-level loopback-only HTTP; websocket denied; OS network namespace still required"}
    browser=None
    try:
        with sync_playwright() as p:
            chromium=os.environ.get("CHROMIUM_PATH","").strip()
            launch={"headless":True}
            if chromium:launch["executable_path"]=chromium
            browser=p.chromium.launch(**launch)
            ctx=browser.new_context(accept_downloads=False,service_workers="block",permissions=[],
                                     java_script_enabled=True,ignore_https_errors=False)
            install_network_policy(ctx,result,port)
            page=ctx.new_page()
            page.on("console",lambda msg: result["console_errors"].append(msg.text) if msg.type=="error" else None)
            page.on("pageerror",lambda ex:result["console_errors"].append(str(ex)))
            page.on("requestfailed",lambda req:result["failed_requests"].append(req.url))
            page.on("response",lambda response:result["http_errors"].append(
                {"url":response.url,"status":response.status}) if response.status>=400 else None)
            page.goto("http://127.0.0.1:"+str(port)+"/__isolated_smoke_host__",
                      wait_until="domcontentloaded",timeout=timeout_ms)
            page.locator("iframe").wait_for(timeout=timeout_ms)
            page.wait_for_timeout(1500)
            child=next((f for f in page.frames if f!=page.main_frame and f.url.endswith("/"+entry)),None)
            if child:
                try:
                    result["frame_body_loaded"]=child.locator("body").count()>0
                    result["iframe_isolation"]=child.evaluate(
                        "() => {try{void parent.document.body;return false}catch(e){return true}}")
                except Exception as exc:result["console_errors"].append("frame probe: "+str(exc))
            if screenshot:
                screenshot.parent.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(screenshot),full_page=True)
                result["screenshot"]=str(screenshot)
            load_ok=(result["frame_body_loaded"] and result["iframe_isolation"]
                     and not result["console_errors"] and not result["blocked_requests"]
                     and not result["blocked_websockets"] and not result["failed_requests"]
                     and not result["http_errors"])
            result["status"]="BROWSER_LOAD_CHECKED" if load_ok else "INCOMPLETE_OR_FAILED"
            ctx.close()
            browser.close()
            browser=None
    finally:
        if browser:browser.close()
        server.shutdown();server.server_close();thread.join(timeout=3)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True,help="Local static files root")
    p.add_argument("--entry",required=True,help="HTML path inside root")
    p.add_argument("--screenshot",type=Path)
    p.add_argument("--report",type=Path)
    args=p.parse_args()
    info=smoke(args.root,args.entry,args.screenshot)
    result=json.dumps(info,ensure_ascii=False,indent=2)
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(result+"\n",encoding="utf-8")
    print(result)
    if info["status"]!="BROWSER_LOAD_CHECKED":raise SystemExit(1)

if __name__=="__main__":main()
