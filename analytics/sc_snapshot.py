"""Search Console indexing snapshot for the Global News Map (SMA-543).

Runs the URL Inspection API over every URL in the live sitemap and writes a
cached summary to analytics/sc_snapshot.json. ga_report.py reads the cache
(fresh if < 48h) so the daily loop readout shows an indexed-page count and
top queries without paying the ~4 minute inspection cost every run.

Usage: .venv/bin/python analytics/sc_snapshot.py
Auth: same service account as gauth.get_token; needs webmasters.readonly.
The SA has siteFullUser on sc-domain:globalnewsmap.net.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gauth import get_token

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
SITE_URL = "sc-domain:globalnewsmap.net"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sc_snapshot.json")
SITEMAP = "https://globalnewsmap.net/sitemap.xml"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}  # urllib UA gets 403


def inspect_url(url, headers, tries=4):
    for t in range(tries):
        try:
            req = urllib.request.Request(
                "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                data=json.dumps({"inspectionUrl": url, "siteUrl": SITE_URL}).encode(),
                headers=headers)
            return json.load(urllib.request.urlopen(req, timeout=45))
        except Exception as e:
            if t == tries - 1:
                return {"error": repr(e)[:200]}
            time.sleep(4)


def fetch_sitemap(tries=5):
    """Fetch the sitemap XML via curl (SMA-550). urllib's read pattern
    consistently hits IncompleteRead ~16KB in through the egress proxy
    while curl (preemptive Proxy-Authorization) succeeds every time."""
    import subprocess
    for t in range(tries):
        try:
            p = subprocess.run(
                ["curl", "-sS", "-A", UA["User-Agent"], "--max-time", "30", SITEMAP],
                capture_output=True, timeout=40, check=True)
            return p.stdout.decode()
        except Exception as e:
            if t == tries - 1:
                raise
            print("sitemap fetch retry", t + 1, repr(e)[:100], flush=True)
            time.sleep(5)


def main():
    token = get_token(SCOPES)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    xml = fetch_sitemap()
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    # SMA-656: a single inspection takes ~7s through the egress proxy, so the
    # old serial loop (165 URLs x ~8s) needed ~22 min and wrote only once at
    # the very end — the detached auto-refresh (SMA-573) never survived that
    # long in this VM, and the snapshot stayed frozen at the last committed
    # version (2026-10-08) for 13 days despite daily kicks. Inspect in
    # parallel (URL Inspection quota is 600/min; 8 workers is far under it)
    # so a full refresh lands in ~3 min, and write the result atomically so
    # readers never see a partial file.
    from concurrent.futures import ThreadPoolExecutor

    def _inspect(u):
        r = inspect_url(u, headers)
        isr = (r.get("inspectionResult") or {}).get("indexStatusResult", {}) \
            if isinstance(r, dict) else {}
        return {"url": u, "verdict": isr.get("verdict"),
                "coverage": isr.get("coverageState") or "error",
                "lastCrawl": isr.get("lastCrawlTime")}

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_inspect, urls))
    coverage = {}
    for r in results:
        coverage[r["coverage"]] = coverage.get(r["coverage"], 0) + 1
    indexed = sum(1 for r in results if r["coverage"] == "Submitted and indexed")
    snapshot = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sitemap_urls": len(urls),
                "indexed": indexed,
                "by_coverage": coverage,
                "results": results}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f)
    os.replace(tmp, OUT)
    # Clear our own auto-refresh pid file so a stale pid never blocks a kick.
    try:
        pid_path = OUT + ".refresh.pid"
        with open(pid_path) as f:
            if int(f.read().strip()) == os.getpid():
                os.remove(pid_path)
    except Exception:
        pass
    print(f"snapshot: {indexed}/{len(urls)} indexed -> {OUT}")
    print(json.dumps(coverage, indent=1))


if __name__ == "__main__":
    main()
