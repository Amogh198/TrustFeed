"""Measure the offline link checks on real reported phishing addresses, without opening any.

    python -m backend.text.evaluation.run_link_feed_eval --write

Reads OpenPhish's public feed as text. No listed page is visited, and no address is saved.
The ordinary side is a hand-written list of well-known sites, so it is small and easy.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

os.environ["LINK_THREAT_FEEDS"] = "off"

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.app.main import app  # noqa: E402
from backend.provenance.safe_http import safe_request  # noqa: E402
from backend.text.links import THREAT_FEEDS  # noqa: E402

ORDINARY = """wikipedia.org youtube.com github.com stackoverflow.com bbc.com reuters.com nytimes.com thehindu.com
ndtv.com irctc.co.in nasa.gov who.int flipkart.com zomato.com swiggy.com linkedin.com reddit.com medium.com
python.org mozilla.org cloudflare.com adobe.com spotify.com airbnb.com booking.com ebay.com walmart.com
indiatimes.com hindustantimes.com gov.in uidai.gov.in rbi.org.in npci.org.in dropbox.com zoom.us slack.com
notion.so figma.com canva.com wordpress.org archive.org nature.com arxiv.org coursera.org khanacademy.org
freecodecamp.org wikihow.com gofundme.com imdb.com espn.com""".split()
CAVEATS = [
    "This is the offline address check alone. Live page checks and the threat feeds are not included.",
    "Phishing addresses are real but only what OpenPhish currently lists. Ordinary sites are 50 famous names, far easier than typical traffic.",
    "Flagged means moderate or above.",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    body = safe_request(THREAT_FEEDS["OpenPhish"], max_bytes=5_000_000, max_redirects=2, headers={"User-Agent": "TrustFeed-LinkCheck/1.0"}).body
    phish = [line.strip() for line in body.decode("utf-8", "replace").splitlines() if line.startswith("http")][:500]
    client = TestClient(app)

    def flagged(url: str) -> bool:
        response = client.post("/api/cases/analyze", json={"url": url})
        return response.status_code == 200 and response.json()["overall_risk"] in {"moderate", "high", "critical"}

    caught = sum(flagged(url) for url in phish)
    false_alarms = [site for site in ORDINARY if flagged(f"https://www.{site}/")]
    result = {
        "measured_on": datetime.now(UTC).date().isoformat(),
        "phishing_flagged": f"{caught} of {len(phish)}",
        "recall": round(caught / len(phish), 3) if phish else None,
        "ordinary_flagged": f"{len(false_alarms)} of {len(ORDINARY)}",
        "ordinary_false_alarms": false_alarms,
        "caveats": CAVEATS,
    }
    print(json.dumps(result, indent=2))
    if args.write:
        (Path(__file__).parent / "results" / "link_eval_feed.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
