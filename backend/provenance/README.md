# Image source search (T1)

Finds where an image appeared on the web, and when, using reverse image search. The result is a list of pages with dates, plus the earliest appearance the searches found.

**This never shows where an image came from.** The earliest result is only the earliest one found. The true source may be older or elsewhere. A match says nothing about whether a claim about the image is true. The score is always null.

## Privacy

- The image only leaves the server when the caller passes `search_web=True` **and** a provider has a key. A key alone sends nothing.
- Only re-encoded pixels are sent, so EXIF data such as GPS location is not.
- File names, URLs, uploaded content and page text are not logged.
- Faces are not identified. Nothing here looks at who is in an image.

## Use

```python
from backend.provenance import investigate_provenance

report = investigate_provenance("photo.jpg", search_web=True)
report.status             # complete, unavailable or not_applicable
report.appearances        # each with page_url, match_type, observed_at, date_source, date_evidence
report.earliest_found     # None if nothing has a usable date
report.to_module_result() # the shared ModuleResult shape, score and confidence null
report.timeline_events()  # undated appearances stay in, with a null time
```

Expected failures return `status="unavailable"` with a reason. They do not raise.

From the command line:

```bash
python -m backend.provenance search photo.jpg
```

```bash
python -m backend.provenance search photo.jpg --web
```

The first command checks only the local reference list. The second sends the image to every provider with a key.

## Providers

Each provider without a key is skipped. If one fails, the others still run.

Keys are read from environment variables, and **`.env` is not loaded automatically**. Put keys in `.env`, which Git ignores, then start the API with:

```bash
python -m uvicorn backend.api.app.main:app --env-file .env
```

For the command-line tool, set the variable in your shell first.

| Variable | Service | Gives | Dates |
| --- | --- | --- | --- |
| `GOOGLE_VISION_API_KEY` | [Google Vision Web Detection](https://cloud.google.com/vision/docs/detecting-web) | pages and images | none, so page dates are read |
| `TINEYE_API_KEY` | [TinEye API](https://services.tineye.com/developers/tineyeapi/) | pages and images | crawl date |
| `SERPAPI_API_KEY` | [SerpApi Google Lens exact matches](https://serpapi.com/google-lens-exact-matches-api) | pages | only vague text such as "2 years ago", never used as a date |

The local list from `MEDIA_PHASH_INDEX` also runs, and never uses the network.

Only SerpApi has been run for real, on 2026-11-05, through the upload route with two openly licensed images. An AI-generated image found no pages. A historic postcard found 25 pages, 17 of them exact matches, with 8 usable dates, in 30 seconds. Google Vision and TinEye have only been tested against fakes.

SerpApi's free plan allows 250 searches a month. Each uploaded image with `search_web` now uses two: one for exact matches and one for visual matches. Set `SERPAPI_VISUAL_MATCHES=false` to use one.

### Similar pictures

SerpApi's visual matches are reported as `match_type: "similar"`, in their own `provenance.similar` check. They are pictures that look alike, not copies, and can show an unrelated picture. They aren't counted in `provenance.search`, can't become "earliest found" unless the hash shows the same image, and never change any detector score. No search result does.

The visual matches haven't been run against the live service, to save credits. The tests use mocked responses in the documented format. If the visual search fails, exact matches are kept, and the report says so.

### Credit check

Before sending anything, SerpApi's free [Account API](https://serpapi.com/account-api) is asked how many searches are left. A check costs no search. If too few are left, or the count can't be confirmed, the image isn't sent, nothing is spent, and the provider reports `unavailable`. Only the count is read. The response also holds the key and account email, so it is never logged, stored or returned.

### Results cache

Results are saved by the file's SHA-256 and provider, so searching the same file again spends nothing, and the report says saved results from which date were reused.

- **Where:** `PROVENANCE_CACHE_DIR`, by default `.cache/trustfeed/provenance` in the home folder. Results stay for 30 days.
- **What:** only the found links, titles and dates. File names are hashed, so neither the image nor its SHA-256 appears, and no key is stored.
- **Not saved:** failed searches and partial answers.
- **Keep it private.** The results show what someone searched for. Saved results are cleaned again when read, because they count as untrusted too.

### Per-site delays

Page and image requests to one site are at least 1 second apart. A site's `Crawl-delay` in `robots.txt` can raise that to at most 10 seconds. A wait that would pass the time limit gives up instead of sleeping.

TinEye is called over REST directly. The official `pytineye` 3.0.0 client pins `urllib3==1.26.6`, `certifi==2021.5.30` and `future==0.18.2`, which are too old to install beside the API's dependencies.

## How dates are chosen

1. JSON-LD `datePublished` on the page.
2. Open Graph `article:published_time`.
3. The HTTP `Last-Modified` header, labelled as the weakest hint.

If a crawl date is earlier than the page's date, the crawl date wins, because a crawler cannot see an image before it exists. Each result says where its date came from in `date_source` and `date_evidence`. A result with no date stays in the list with `observed_at: null`, and no date is ever invented.

Dates describe the page or the crawl, not the image. A page can state a date falsely, and an old page can have a new image added to it.

## How matches are checked

Where the matching image can be downloaded, its perceptual hash is compared with the upload, and `phash_distance` is reported.

- TinEye results become `exact` at distance 5 or less, otherwise `partial`.
- A provider's `exact` result at a distance above 12 is downgraded to `similar`.
- A `similar` result can only be the earliest if the hash shows it is the same image.

If the image cannot be downloaded, `phash_distance` is null and the report says so.

## Untrusted content

Search results and web pages are untrusted data, and are never followed as instructions.

- `safe_http.py` allows only http and https on ports 80 and 443, and refuses URLs with embedded credentials.
- It checks every address when connecting, including after redirects, so private and metadata addresses cannot be reached.
- It limits size, time, redirects and gzip expansion. It ignores proxy settings.
- `robots.txt` is respected. If it is unreachable or returns a server error, the page is not read.
- Titles have control characters removed, but **may still contain HTML or misleading text**. Show them as plain text and never render them as HTML.
- Only http and https links are kept, so a `javascript:` link cannot reach the dashboard.

## Replay and demo

Replay never touches the network.

- `get_demo_provenance("demo-001")` returns the invented demo report. It is labelled `synthetic: true` and uses reserved `.example` domains. Its hash, `742dc2b3587a83a2`, is also in `data/demo/network_demo.json`, so the demo can link the two.
- `PROVENANCE_REPLAY_PATH=data/demo/provenance_demo.json` makes searches read recorded results. An image with no recording returns `unavailable`.

To record a real search of a freely licensed image for the demo:

```bash
python -m backend.provenance record photo.jpg --licence "CC0" --attribution "Who made it, and the page it came from"
```

This refuses to save anything unless a live search completed. Check the recording before committing it, because it holds real page links.

## Explanation check

`report.to_checks()` returns a `provenance.search` entry and a `provenance.similar` entry, in the draft `/explanation` check shape. Their `benchmark` is always `null`, because search coverage has not been measured. They keep the synthetic and replay labels and the "earliest found" caveat.

## Limits

- A search covers only what these services have indexed. Private groups, deleted pages and much of social media are missing. Finding nothing does not show that an image is new or genuine.
- Images only. Videos return `unavailable`.
- Up to 25 results are checked, within 20 seconds.
- **It can be slow.** Providers run one after another, up to 20 seconds per call, so three keys could take about 100 seconds in the worst case. Call it where a long wait is acceptable.

## Tests

```bash
python -m pytest backend/provenance -q -p no:cacheprovider
```

The tests need no keys, and any attempt to use the network fails them.
