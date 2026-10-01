"""Resubmit the sitemap via the Search Console API (SMA-550).

Tells Google to re-fetch https://globalnewsmap.net/sitemap.xml now, so the
88 "Discovered - currently not indexed" country/region pages get re-queued
sooner. Auth: same service account as gauth.get_token (siteFullUser on
sc-domain:globalnewsmap.net); needs the webmasters scope (submit is
write, readonly won't do).

Usage: .venv/bin/python analytics/submit_sitemap.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gauth import get_token

SCOPES = ["https://www.googleapis.com/auth/webmasters"]
SITE_URL = "sc-domain:globalnewsmap.net"
SITEMAP_URL = "https://globalnewsmap.net/sitemap.xml"


def main():
    token = get_token(SCOPES)
    url = (
        "https://www.googleapis.com/webmasters/v3/sites/"
        + urllib.parse.quote(SITE_URL, safe="")
        + "/sitemaps/"
        + urllib.parse.quote(SITEMAP_URL, safe="")
    )
    # The webmasters v3 sitemaps.submit endpoint wants a PUT with a (possibly
    # empty) JSON body: no body -> 411 from the proxy path, a Sitemap resource
    # body -> 400 unknown field. An empty object returns 204 on success.
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        print("resubmitted:", resp.status)
        body = resp.read().decode()
        if body:
            print(body[:600])
    except urllib.error.HTTPError as e:
        print("HTTPError", e.code, e.read().decode()[:600])
        sys.exit(1)
    except Exception as e:
        print("ERROR", repr(e)[:300])
        sys.exit(1)


if __name__ == "__main__":
    main()
