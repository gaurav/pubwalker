"""uv run pubwalker <step|all> <doi> [--n 40] [--seed 1]. Steps are idempotent and cached."""
import argparse

from . import analyze, export, fetch, passages

STEPS = {
    "fetch": lambda a: fetch.run(a.doi),
    "passages": lambda a: passages.run(a.doi, n=a.n, seed=a.seed),
    "roles": lambda a: analyze.roles(a.doi),
    "synth": lambda a: analyze.synth(a.doi),
    "structure": lambda a: analyze.structure(a.doi),
    "compare": lambda a: analyze.compare(a.doi),
    "export": lambda a: export.run(a.doi),
}


def main():
    p = argparse.ArgumentParser(prog="pubwalker", description=__doc__)
    p.add_argument("step", choices=[*STEPS, "all"])
    p.add_argument("doi")
    p.add_argument("--n", type=int, default=40, help="citers sampled per time window")
    p.add_argument("--seed", type=int, default=1)
    a = p.parse_args()
    for name in (STEPS if a.step == "all" else [a.step]):
        print(f"== {name}")
        STEPS[name](a)


def serve():
    """uv run serve [port]: serve site/ and reload the browser when a file in it changes."""
    import sys

    from livereload import Server  # dev dependency

    from . import SITE_DATA

    server = Server()
    server.watch(str(SITE_DATA.parent))
    server.serve(root=str(SITE_DATA.parent), port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765)


def screenshot():
    """uv run screenshot <out.png> [doi] [tab] [width]: render site/ in headless Chromium (playwright, dev dependency) and save a
    full-page screenshot; console errors are printed. Serves site/ itself on a free port, so nothing else needs to be running."""
    import http.server
    import sys
    import threading
    from functools import partial

    from playwright.sync_api import sync_playwright

    from . import SITE_DATA

    out, doi, tab, width = (sys.argv[1:] + [None] * 4)[:4]
    quiet = type("Quiet", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(quiet, directory=str(SITE_DATA.parent)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/" + (f"?doi={doi}&tab={tab or 'backscatter'}" if doi else "")
    with sync_playwright() as p:
        page = p.chromium.launch().new_page(viewport={"width": int(width or 1200), "height": 900})
        page.on("console", lambda m: m.type == "error" and print(f"console error: {m.text}", file=sys.stderr))
        page.on("pageerror", lambda e: print(f"page error: {e}", file=sys.stderr))
        page.goto(url)
        page.wait_for_selector(".tabs.top" if doi else "form.live")  # rendered by app.js once data has loaded
        page.screenshot(path=out or "site.png", full_page=True)
    print(f"wrote {out or 'site.png'} from {url}")


if __name__ == "__main__":
    main()
