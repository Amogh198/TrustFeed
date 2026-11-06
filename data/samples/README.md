# Sample data for testing

Everything here is **invented**. Links use the reserved `.example` ending, so they can't reach a real site. These samples show whether the app works. They say nothing about its accuracy.

Run this from the repository root to rewrite the files and compare each sample with its expected result. It stays offline:

```bash
python data/samples/run_samples.py
```

| File | Tests | How to use it |
|---|---|---|
| `cases.json` | Scam signs, unified risk, language rules, inconsistencies, Hindi | Paste `text` and `url` into the Check page, and compare with `expected_risk` |
| `links.json` | Lookalike domains, and real brand domains that must not be flagged | Paste a `url` into the Check page's link box |
| `cross_modal.json` | Caption against on-screen text and speech | Script only, until the media check sends this text |
| `network_tight_group.json` | Shuffled-timing test should find more than chance | Script only |
| `network_one_news_moment.json` | Everyone posting at once should give no signal | Script only |
| `network_ordinary_posts.json` | Nothing to test | Script only |
| `network_reused_images.json` | Near-identical fingerprints should count as one image | Script only |
| `images/` | Upload flow and the report | Upload on the Check page. They have no expected result, as the detector isn't tested here |

Leave "Also search the public web and platforms" unticked for these. `links.json` has two real domains, and ticking the box would open them and send your text to outside services.

Not covered: real fakes for the media detector, redirects, domain age and page reading, which need live sites.
