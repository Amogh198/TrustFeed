# Media forensics adapter (T1)

Analyzes one image or video and returns explainable evidence: model signal, metadata, perceptual-hash provenance and sampled keyframes.

**A model score is a triage signal, not proof that media is authentic or false.** There is deliberately no real/fake output.

## Setup

Run these from the repository root, on Python 3.11 or newer.

```bash
pip install -r backend/media/requirements.txt
```

```bash
pip install -r backend/media/requirements-model.txt
```

```bash
python -m backend.media download-model
```

The second and third steps are optional and enable the classifier. The download fetches about 343 MB of `model.safetensors` plus config files, pinned to one revision. Do it before the event: analysis itself never downloads weights unless `MEDIA_ALLOW_MODEL_DOWNLOAD=true`.

## Use

```python
from backend.media import analyze_media

result = analyze_media("sample.jpg")
result.to_module_result()  # shared contract shape, for `modules.media`
result.model_dump(mode="json")  # full evidence, including per-keyframe detail
```

```bash
python -m backend.media index-add old_photo.jpg --index media_index.json --label "2019 flood photo" --first-seen 2019-08-10 --source "Sample archive"
```

```bash
python -m backend.media analyze sample.jpg --index media_index.json
```

`analyze_media` reports expected failures in the result instead of raising. The command line exits with `2` when the input was rejected.

## Output

`to_module_result()` returns the `API_CONTRACTS.md` module shape:

| Field | Meaning |
|---|---|
| `status` | `complete` when a model result exists. Otherwise `unavailable`, which can still carry metadata and pHash evidence. |
| `score` | Model signal for the synthetic class, 0 to 1. `null` when no model result exists, never a placeholder. |
| `confidence` | Always `null`, because the model's probabilities are not calibrated. |
| `evidence` | Plain-text findings. |
| `limitations` | What was not checked and why results may be unreliable. |

The full result adds:

- `assessment`: `signals_present`, `no_strong_signals` or `inconclusive`
- `failure_code`: `not_found`, `empty_file`, `unsupported_type`, `too_large`, `corrupt_media`, `unreadable` or `dependency_missing`
- `sha256` and `size_bytes`
- `checks`: `metadata`, `classifier`, `phash` and `keyframes`, each with its own status

### How results are decided

- **Model bands:** 0.75 or above is elevated, 0.25 or below is low, and anything between is inconclusive.
- **Inconclusive overrides:** images under 128 px on a side, and videos whose keyframe scores differ by 0.5 or more.
- **Video score:** the mean of the strongest third of keyframes.
- **Signals present:** an elevated model band, a pHash match within Hamming distance 5, or metadata naming an image generator. Editing-software tags are reported but do not count as a signal.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MEDIA_MODEL_ID` | `dima806/deepfake_vs_real_image_detection` | Hugging Face ID or local folder. Weights must be safetensors. |
| `MEDIA_MODEL_REVISION` | Pinned commit | Revision for the model. |
| `MEDIA_ALLOW_MODEL_DOWNLOAD` | `false` | Lets analysis download missing weights. |
| `MEDIA_DEVICE` | `auto` | `cuda`, `cpu` or `auto`. |
| `MEDIA_PHASH_INDEX` | Not set | Path to the JSON reference index. |

## Tests

```bash
python -m pytest backend/media/tests
```

Tests use generated media and a stub or tiny random model, so they need no downloaded weights. Scores from the tiny model mean nothing; it only exercises the loading code. `test_real_model.py` runs the pinned model when its weights are present and is skipped otherwise. It checks that the model runs, not how accurate it is.

## Measuring accuracy

```bash
python -m backend.media.eval --real DIR --fake DIR --out data/eval/RESULT.json --source "name|licence|url"
```

Subfolders become categories, such as `DIR/face_swap`. Add `--compare org/name@<commit>` to measure another model on the same images, after downloading it with `MEDIA_MODEL_ID` and `MEDIA_MODEL_REVISION` set and `python -m backend.media download-model`.

The results file holds only counts and scores, never images or file names. **Never commit images.** For each model and category it reports:

- Recall, false positive rate and inconclusive rate, each with a 95% Wilson interval. An inconclusive result counts as not flagged.
- The confusion matrix, score histogram and AUC.
- `too_few_to_conclude`, when a class has under 30 images.
- The best single threshold, chosen on the calibration split and measured only on the test split. Copies with the same pHash stay in one split.

`--source` is required, because a result must say what its data is and what allows its use. The tool records this statement but can't verify it.

To build a set from images with open licences, keeping a manifest of each file's page, licence and author:

```bash
python -m backend.media.eval.fetch_commons --out C:/Projects/samples --per-category 150
```

```bash
python -m backend.media.eval.recompress --in C:/Projects/samples/real --out C:/Projects/samples/recompressed/real
```

Both refuse to write inside the repository. Commons labels come from human-curated categories, so some can be wrong. Real photos are limited to uploads before 2020 to reduce the chance of generated images among them.

### Results from 2026-11-05

**At its current settings, the detector almost never flags a fake.** Across all 301 fake images it flagged 3, and it scored 236 of them `low`, so a `low` result says very little. The model's scores do separate fake from real, but they run low: 78% of fake images score under 0.25, the top of the `low` band, and only 3 reach 0.75, the start of the flagged band.

The set has 452 images from Wikimedia Commons: 150 AI-generated, 150 edited and 150 real photos of people, plus one labelled face-swap pair. These figures come from the test split only, which has 157 fake and 75 real images. Brackets show the 95% interval.

| Model | AUC | Flagged at current bands: fakes | Flagged at current bands: real | Best threshold | Fakes above it | Real above it |
|---|---|---|---|---|---|---|
| `dima806/deepfake_vs_real_image_detection` (in use) | 0.85 | 1 of 157 | 1 of 75 | 0.0068 | 82% [75–87] | 19% [11–29] |
| `prithivMLmods/open-deepfake-detection` | 0.46 | 16 of 157 | 22 of 75 | 0.2724 | 80% [73–85] | 69% [58–79] |
| `Ateeqq/ai-vs-human-image-detector` | 0.56 | 88 of 157 | 43 of 75 | 0.9989 | 46% [38–54] | 23% [15–33] |

- Neither alternative beats the model in use. An AUC near 0.5 is close to guessing.
- Recompressing every image as a low-quality JPEG barely changed the model in use: AUC 0.85, and at its own best threshold of 0.0101, 78% of fakes [71–84] and 15% of real photos [9–24] on a test split of 156 fake and 81 real.
- The bands in the code are unchanged. These thresholds are measurements, not settings in use.

What these figures can't show:

- **Face swaps are unmeasured.** The set has one labelled pair, so the result is marked too few to conclude.
- **False positives were measured only on photos of people.** The downloader crashed on its last category, real landscapes, animals and architecture, so that category was never fetched. This bug is now fixed.
- **Video and images re-saved by social media platforms are unmeasured.**
- Results on this set don't predict results on other kinds of image, and no score proves that an image is authentic or false.

**This run has no per-file licence list.** Each file's licence was checked before download, but the same crash stopped the manifest being written. The tool now writes it after each category. The next full run will produce one.

Full results are in `data/eval/commons_2026-11-05.json` and `data/eval/commons_recompressed_2026-11-05.json`.

## Limitations

- The classifier flags very few fakes at its current bands, as "Results from 2026-11-05" shows, so a `low` result is not reassuring. On Windows stock wallpapers it scored between 0.20 and 0.73, so mid-range scores should not be read as a signal.
- Input limits: images up to 25 MB and 50 megapixels, videos up to 200 MB. Older QuickTime files without an `ftyp` header are rejected as unsupported.
- Video analysis looks at keyframes only, up to 16 from the first 10 minutes. It does not check audio, lip sync or motion between frames.
- Video metadata covers stream properties only, not container tags.
- pHash can only match references already in the index, and a non-match says nothing about originality.
- GPS coordinates are never returned, only whether GPS data exists.
- EXIF-derived evidence text comes from the uploaded file, so the UI must escape it before display.
- JSON index lookups scan every entry, which is fine for a demo-sized index.
