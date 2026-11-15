"""Read-only browser view of the swarm's output. Standard library only.

    python3 swarm/dashboard.py          # then open http://127.0.0.1:8765

Shows what the agents have written to disk: lanes (per domain and per item),
the ranked discoveries, prototype plans, coherence tables and git changes.
It cannot see agents that are still thinking; for that use /workflows in the
Claude session.
"""
import html
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SW = ROOT / "swarm"


def git(*a):
    try:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout
    except Exception as e:  # noqa: BLE001
        return f"git failed: {e}"


def lanes():
    out = {}
    base = SW / "lanes"
    if not base.exists():
        return out
    for item in base.glob("*/*/*"):
        if not item.is_dir():
            continue
        domain = item.parent.parent.name
        files = [p for p in item.rglob("*") if p.is_file()]
        out.setdefault(domain, []).append({
            "id": f"{item.parent.parent.name}.{item.parent.name}.{item.name}",
            "files": len(files),
            "provenance": (item / "PROVENANCE.json").exists(),
            "integration": (item / "INTEGRATION.md").exists(),
        })
    return out


def page():
    ls = lanes()
    total = sum(len(v) for v in ls.values())
    disc = []
    dp = SW / "discoveries.json"
    if dp.exists():
        try:
            data = json.loads(dp.read_text())
            disc = data if isinstance(data, list) else data.get("candidates", data.get("ranked", []))
        except Exception:  # noqa: BLE001
            disc = []
    protos = sorted((SW / "discoveries").glob("*.md")) if (SW / "discoveries").exists() else []
    coh = sorted((SW / "coherence").glob("*.md")) if (SW / "coherence").exists() else []
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(d)}</td><td>{len(v)}</td><td>{sum(x['provenance'] for x in v)}</td><td>{sum(x['integration'] for x in v)}</td><td>{sum(x['files'] for x in v)}</td></tr>"
        for d, v in sorted(ls.items()))
    drows = "".join(
        f"<tr><td>{i+1}</td><td><a href='{e(str(c.get('url','')))}' target=_blank>{e(str(c.get('name','')))}</a></td>"
        f"<td>{e(str(c.get('domain','')))}</td><td>{e(str(c.get('licence','')))}</td><td>{e(str(c.get('realism_gain','')))}</td>"
        f"<td>{e(str(c.get('igpu_cost','')))}</td><td>{e(str(c.get('what_it_adds',''))[:140])}</td></tr>"
        for i, c in enumerate(disc[:200]) if isinstance(c, dict))
    return f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=15>
<title>Swarm</title><style>
body{{font:14px system-ui;margin:24px;max-width:1100px;background:#0f1115;color:#e6e6e6}}
table{{border-collapse:collapse;width:100%;margin:8px 0 24px}}td,th{{border-bottom:1px solid #2a2f3a;padding:6px 8px;text-align:left}}
a{{color:#7ab7ff}}pre{{background:#171a21;padding:12px;overflow:auto}}.big{{font-size:28px}}</style>
<h1>Swarm output <small>(refreshes every 15 s)</small></h1>
<p class=big>{total} lanes written &middot; {len(disc)} discoveries &middot; {len(protos)} prototype plans &middot; {len(coh)} coherence tables</p>
<h2>Lanes by domain</h2><table><tr><th>domain<th>lanes<th>with PROVENANCE<th>with INTEGRATION<th>files</tr>{rows or '<tr><td colspan=5>none yet</td></tr>'}</table>
<h2>Ranked discoveries</h2><table><tr><th>#<th>name<th>domain<th>licence<th>gain<th>iGPU cost<th>adds</tr>{drows or '<tr><td colspan=7>swarm/discoveries.json not written yet</td></tr>'}</table>
<h2>Prototype plans</h2><p>{'<br>'.join(e(p.name) for p in protos) or 'none yet'}</p>
<h2>Coherence tables</h2><p>{'<br>'.join(e(p.name) for p in coh) or 'none yet'}</p>
<h2>Git: branch {e(git('branch','--show-current').strip())}</h2><pre>{e(git('status','--short')[:6000]) or 'clean'}</pre>
"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = page().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), H).serve_forever()
