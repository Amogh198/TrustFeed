"""Write the synthetic sample files and check each against what it should do. Stays offline.

    python data/samples/run_samples.py

Everything here is invented. Links use the reserved .example ending, so none can reach a real
site. These samples test that the app works. They say nothing about its accuracy.
"""

import json
import os
import random
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
os.environ["CASE_STORE_PATH"] = str(Path(tempfile.mkdtemp()) / "samples.db")

# name, text, link, expected overall_risk
CASES = [
    ("job_scam", "Pay a registration fee of Rs 500 to get this work from home job. Send your OTP now.", None, "high"),
    ("prize_scam", "You have won a lottery! Click here to claim your prize and share your bank details today.", None, "high"),
    ("investment_scam", "Guaranteed returns! Double your money in 7 days. Send your investment to my UPI now.", None, "high"),
    ("scam_and_lookalike", "Your account is blocked. Send your OTP now to verify your account.", "https://paypa1.example/login", "critical"),
    ("lookalike_only", None, "https://secure-paypal.example/", "high"),
    ("plain_notice", "The library opens at nine on weekdays.", None, "low"),
    ("plain_with_link", "The town meeting is on Tuesday evening.", "https://town-notices.example/meeting", "low"),
    ("conspiracy_language", "Officials are hiding the truth about this. Share this now!", None, "inconclusive"),
    ("health_language", "This miracle cure cures cancer in three days.", None, "inconclusive"),
    ("inconsistent_figures", "The fire killed 50 people in the market on 3 March 2024. The fire killed 200 people in the market on 3 March 2024.", None, "inconclusive"),
    ("hindi_urgency", "यह संदेश तुरंत सबको भेजें।", None, "inconclusive"),
]
LINKS = [
    ("https://paypa1.example/signin", "paypal", "strong"),
    ("https://arnazon.example/", "amazon", "strong"),
    ("https://gooogle.example/", "google", "strong"),
    ("https://netflix-billing.example/", "netflix", "strong"),
    ("https://sbi-kyc-update.example/", "sbi", "strong"),
    ("https://paypal.com.account-check.example/", "paypal", "strong"),
    ("https://paypal.example.org/", "paypal", "weak"),
    ("https://amazon-rainforest.example/", "amazon", "weak"),
    ("https://town-notices.example/", None, None),
    ("https://www.paypal.com/signin", None, None),
    ("https://onlinesbi.sbi/", None, None),
]
CROSS_MODAL = [
    ("dates_differ", "Flood hit the town on 3 March 2024.", {"ocr": ["Recorded on 12 June 2019"], "speech": []}, "notes_only"),
    ("negation", "The minister resigned from the cabinet yesterday.", {"ocr": [], "speech": ["The minister did not resign from the cabinet yesterday."]}, "conflicts_found"),
    ("figures", "The fire killed 50 people in the market.", {"ocr": ["The fire killed 200 people in the market."], "speech": []}, "conflicts_found"),
    ("matching", "The bridge collapsed on 3 March 2024.", {"ocr": ["The bridge collapsed on 3 March 2024."], "speech": []}, "none_found"),
]
START = datetime(2026, 1, 5, 9, tzinfo=UTC)


def _post(posts, account, seconds, url=None, text="", fingerprint=None):
    moment = START + timedelta(seconds=seconds)
    item = {"id": f"p{len(posts)}", "account_id": account, "created_at": moment.isoformat().replace("+00:00", "Z")}
    if url:
        item["url"] = url
    if text:
        item["text"] = text
    if fingerprint:
        item["media_fingerprint"] = fingerprint
    posts.append(item)


def _dataset(name, posts):
    ids = sorted({post["account_id"] for post in posts})
    return {"metadata": {"case_id": f"sample-{name}", "synthetic": True}, "accounts": [{"id": i, "handle": f"@invented_{i}"} for i in ids], "posts": posts}


def network_samples():
    """Each should give a different result from the shuffled-timing test."""
    rng = random.Random(7)
    tight, moment, ordinary, media = [], [], [], []
    for item in range(6):
        for member in range(6):
            _post(tight, f"a{member}", item * 7200 + member, f"https://story.example/{item}")
    for _ in range(40):
        _post(tight, f"bg{rng.randrange(10)}", rng.randrange(36000), f"https://other.example/{rng.randrange(1000)}")
    for item in range(2):
        for member in range(8):
            _post(moment, f"a{member}", item * 3 + member, f"https://news.example/{item}")
    for index in range(60):
        _post(ordinary, f"a{rng.randrange(15)}", rng.randrange(36000), f"https://site.example/{index}")
    for item in range(4):
        base = f"{0xF0F0F0F0F0F00000 + item * 0x1111000000:016x}"
        for member in range(6):
            # The last hex digit differs, as a re-encoded copy's fingerprint would.
            _post(media, f"a{member}", item * 7200 + member, fingerprint=base[:-1] + format(member, "x"))
    return {
        "tight_group": (tight, "above_chance"),
        "one_news_moment": (moment, "not_above_chance"),
        "ordinary_posts": (ordinary, "nothing_observed"),
        "reused_images": (media, "above_chance"),
    }


def make_images():
    from PIL import Image, ImageDraw

    folder = HERE / "images"
    folder.mkdir(exist_ok=True)
    for name, colour, words in (("poster", (30, 60, 120), "SAMPLE: Flood relief, 3 March 2024"), ("chart", (240, 240, 230), "SAMPLE: invented chart")):
        image = Image.new("RGB", (640, 400), colour)
        draw = ImageDraw.Draw(image)
        draw.text((30, 30), words, fill=(255, 200, 0))
        for step in range(6):
            draw.rectangle((60 + step * 90, 350 - step * 40, 120 + step * 90, 360), fill=(200, 70, 90))
        image.save(folder / f"{name}.jpg", quality=90)


def write_files(networks):
    (HERE / "cases.json").write_text(json.dumps([{"name": n, "text": t, "url": u, "expected_risk": r} for n, t, u, r in CASES], ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "links.json").write_text(json.dumps([{"url": u, "brand": b, "strength": s} for u, b, s in LINKS], indent=1), encoding="utf-8")
    (HERE / "cross_modal.json").write_text(json.dumps([{"name": n, "caption": c, "extracted_text": e, "expected": x} for n, c, e, x in CROSS_MODAL], indent=1), encoding="utf-8")
    for name, (posts, verdict) in networks.items():
        (HERE / f"network_{name}.json").write_text(json.dumps({**_dataset(name, posts), "expected_null_test": verdict}, indent=1), encoding="utf-8")


def main():
    from fastapi.testclient import TestClient

    from backend.api.app.main import app
    from backend.network.analysis import analyze_network
    from backend.network.dataset import parse_dataset
    from backend.text.cross_modal import compare_channels
    from backend.text.links import find_lookalike

    networks = network_samples()
    write_files(networks)
    make_images()
    misses = total = 0

    def report(kind, name, got, want):
        nonlocal misses, total
        total += 1
        misses += got != want
        print(f"{'ok  ' if got == want else 'MISS'} {kind:12} {name[:44]:44} got={got} want={want}")

    client = TestClient(app)
    for name, text, url, want in CASES:
        report("case", name, client.post("/api/cases/analyze", json={"text": text, "url": url}).json()["overall_risk"], want)
    for url, brand, strength in LINKS:
        found = find_lookalike(url.split("/")[2])
        report("link", url, (found.brand, found.strength), (brand, strength))
    for name, caption, extracted, want in CROSS_MODAL:
        report("cross_modal", name, compare_channels(caption, extracted).assessment, want)
    for name, (posts, want) in networks.items():
        analysis = analyze_network(parse_dataset(_dataset(name, posts)))
        report("network", name, analysis.tests["null_test"]["verdict"], want)
    print(f"{total - misses} of {total} behaved as expected")


if __name__ == "__main__":
    main()
