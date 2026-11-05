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

### Explanations

`result.to_checks(heatmap_url=None)` returns one entry each for `media.classifier`, `media.metadata`, `media.phash`, `media.keyframes` and `media.fingerprint`: what ran, what it found, why, and how far to trust it. It follows the draft `/explanation` check shape and adds `status`.

- **`benchmark`** holds test-split figures from `data/eval/commons_licensed_2026-11-05.json`, and adds `auc` and counts by band. It is `null` unless that file measured this model and revision at these bands, and it is always `null` for video.
- **Plain statement:** the classifier check's limitations say how few fakes the current bands flag, and whether the detector barely beats guessing.
- **GPS:** the check says GPS data exists but never shows coordinates.

### Fingerprints

Every analysis adds a `media.fingerprint` check. It makes four ImageHash fingerprints (pHash, dHash, wHash and colour hash) for an image or each video keyframe, and uses the file's SHA-256 for exact copies.

**A fingerprint is not a signature.** It can't show who made a file or that it is unchanged. It only shows that pictures look alike. SHA-256 only shows that two files are byte-for-byte the same.

```bash
python -m backend.media index-add old_photo.jpg --index media_index.json --label "2019 flood photo" --first-seen 2019-08-10
```

```bash
python -m backend.media analyze sample.jpg --index media_index.json --cases case_fingerprints.json --remember case-123
```

```python
from backend.media.fingerprint import remember_fingerprints

remember_fingerprints(result, "case-123", path)
```

- **Exact copy:** the SHA-256 is the same.
- **Likely the same image:** at least two of these agree: pHash within 17, dHash within 16, wHash within 7. These limits were chosen on the calibration split, so that any one of them alone matches at most 0.1% of unrelated pairs.
- **Colour hash** is reported but never decides a match. No distance met that target.
- **Earlier cases:** set `MEDIA_CASE_FINGERPRINTS`, or pass `--cases`. The store holds a case ID, a date and hashes, never the image or file name. A hash can still show that someone holds the same file, so keep the store private. `CaseFingerprintStore.remove` deletes a case.
- **Overall result:** a match adds evidence, but doesn't change the score or assessment. The separate `media.phash` check keeps its limit of 5.
- **Blank pictures:** flat images and frames have almost no detail, so they are never matched by fingerprint.
- **Older index files** still load. Entries with only a pHash can't reach two agreeing fingerprints, so add those images again.

Measured on 285 test images, each with simulated changes, and 40,470 unrelated pairs from `data/eval/fingerprints_2026-11-05.json`:

| Change | Two fingerprints agree | pHash at the old limit of 5 |
|---|---|---|
| Recompressed at low quality | 285 of 285 | 283 of 285 |
| Resized to half | 285 of 285 | 283 of 285 |
| Brightened 20% | 285 of 285 | 269 of 285 |
| Cropped 5% each side | 266 of 285 | 13 of 285 |
| Caption bar added | 264 of 285 | 14 of 285 |
| Mirrored | 11 of 285 | 0 of 285 |
| Unrelated pairs wrongly matched | 2 of 40,470 | 0 of 40,470 |

The changes were simulated, not collected from real platforms. Mirrored copies are mostly missed. Some "unrelated" pairs may really be related, such as photos from one series.

To measure again:

```bash
python -m backend.media.eval.fingerprints --real DIR --fake DIR --out data/eval/RESULT.json --source "name|licence|url"
```

### Detector panel

```python
result = analyze_media("sample.jpg", run_panel=True)
```

```bash
python -m backend.media download-panel
```

```bash
python -m backend.media analyze sample.jpg --panel
```

The panel runs six detectors, each pinned, and adds a `media.detector_panel` check. Run it on request, because it took 6 to 14 seconds per image on CPU in a first test. `download-panel` fetches about 2.3 GB of safetensors weights.

- **The overall result doesn't change.** The score, assessment and evidence still come only from the detector in use. Each other detector shows as "shown, not counted", with the measured reason.
- **Memory:** detectors run one at a time and are released before the next one loads.
- **Failures:** a detector that can't run shows as `unavailable` with the reason, and the others carry on.
- **Time limit:** after 180 seconds no further detector starts. One already running finishes.
- **Check shape:** one `detector_result` entry per detector in `artifacts`, with text values for `model_id`, `model_revision`, `status`, `counted` and `why`, plus `score` and `band` when they exist. `benchmark` stays `null`, because that field describes one model.
- **Nonescape:** its weights aren't on Hugging Face, so a SHA-256 pins them, and a file that doesn't match is refused. Its loading code follows the upstream Apache 2.0 repository, and it needs `torchvision`.

### Occlusion heatmap

```python
from backend.media import occlusion_heatmap, render_png

heatmap = occlusion_heatmap(image, classifier)  # about 11 seconds on CPU, images only
png = render_png(heatmap)  # only when heatmap.status is complete
```

```bash
python -m backend.media heatmap sample.jpg --out C:/somewhere-outside-the-repo/heat.png
```

The heatmap covers each of 8 x 8 areas in turn and records how the model's score moves, so it needs 65 model runs. Run it on request, not on every upload. It shows sensitivity, not proof of editing.

- **Colours:** red areas were raising the score and blue areas were lowering it. Colours never scale below a change of 0.05, so tiny changes stay faint.
- **Failure:** if the model fails or 60 seconds pass, the status is `unavailable` with a reason, and there is no partial picture.
- **Privacy:** `render_png` holds only colours, with none of the image's pixels, so it can be stored and laid over the dashboard's own preview. `render_overlay`, used by the command line, holds the image, so never store it. The command refuses to save inside the repository.
- **Timing for the API:** the image is needed, so a route must run this before the temporary upload is deleted.

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
| `MEDIA_CASE_FINGERPRINTS` | Not set | Path to the JSON store of earlier cases' hashes. |

## Tests

```bash
python -m pytest backend/media/tests
```

Tests use generated media and a stub or tiny random model, so they need no downloaded weights. Scores from the tiny model mean nothing; it only exercises the loading code. `test_real_model.py` runs the pinned model when its weights are present and is skipped otherwise. It checks that the model runs, not how accurate it is.

## Measuring accuracy

```bash
python -m backend.media.eval --real DIR --fake DIR --out data/eval/RESULT.json --source "name|licence|url"
```

Subfolders become categories, such as `DIR/face_swap`. Add `--panel` to measure every detector on the panel on the same images, or `--compare org/name@<commit>` for another model, after downloading it with `MEDIA_MODEL_ID` and `MEDIA_MODEL_REVISION` set and `python -m backend.media download-model`.

Add `--scores-cache DIR` to resume a long run. It holds file names, so the command refuses a folder inside the repository.

The results file holds only counts and scores, never images or file names. **Never commit images.** For each model and category it reports:

- Recall, false positive rate and inconclusive rate, each with a 95% Wilson interval. An inconclusive result counts as not flagged.
- The confusion matrix, score histogram and AUC.
- `too_few_to_conclude`, when a class has under 30 images.
- The best single threshold, chosen on the calibration split and measured only on the test split. Copies with the same pHash stay in one split.
- With two or more models, a `comparison`: each model's test AUC with an interval, its difference from the model in use on the same images, a cut-off for few false alarms, each kind of fake against each kind of real, seconds per image, and the best average of detectors. Anything chosen is chosen on the calibration split.

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

**The detector in use barely beats guessing on this set: AUC 0.53, where 0.50 is guessing.** Three other detectors measured better, but none is good enough to settle anything alone. The default detector and its bands are unchanged, and only the detector in use affects the overall result.

The set has 600 images from Wikimedia Commons, with a licence listed for each file: 150 AI-generated, 150 edited, 150 real photos of people, and 150 real landscapes, animals and architecture. The figures below come from the test split only, which has 137 fake and 148 real images. Brackets show the 95% interval.

| Model | AUC | Better than the model in use? | Flagged at current bands: fakes | Flagged at current bands: real | Seconds per image |
|---|---|---|---|---|---|
| `dima806/deepfake_vs_real_image_detection` (in use) | 0.53 [0.46–0.60] | Baseline | 3 of 137 | 3 of 148 | 0.21 |
| `nonescape/nonescape-mini-v0` | 0.69 [0.63–0.75] | Yes | 44 of 137 | 17 of 148 | 0.13 |
| `Ateeqq/ai-vs-human-image-detector` | 0.67 [0.61–0.73] | Yes | 73 of 137 | 46 of 148 | 0.27 |
| `haywoodsloan/ai-image-detector-deploy` | 0.66 [0.60–0.72] | Yes | 35 of 137 | 8 of 148 | 0.77 |
| `prithivMLmods/Deep-Fake-Detector-v2-Model` | 0.50 [0.43–0.57] | No | 16 of 137 | 29 of 148 | 0.22 |
| `prithivMLmods/open-deepfake-detection` | 0.46 [0.39–0.53] | No | 17 of 137 | 24 of 148 | 0.28 |

"Better" means the whole 95% interval of the AUC difference is above zero. Six detectors were compared on one set, so one could look better by chance.

- **A cut-off chosen for few false alarms:** on the calibration split, each detector was given the cut-off that flags at most 5% of real images. On the test split, Ateeqq and haywoodsloan then each caught 33 of 137 fakes, wrongly flagging 7 and 6 of 148 real images. Nonescape mini caught 25, wrongly flagging 9. The model in use caught 8, wrongly flagging 6.
- **A candidate combination:** averaging the model in use, haywoodsloan, Ateeqq and Nonescape mini, chosen on the calibration split, reached AUC 0.72 [0.66–0.78] on the test split, which is 0.19 [0.11–0.27] above the model in use. This isn't in use.
- **The model in use reacts to subject matter.** Against real photos of people its AUC is 0.88 for AI-generated images and 0.79 for edited ones. Against real landscapes, animals and architecture it falls to 0.32 and 0.17, which means those real images tend to score higher than the fakes. The earlier result of 0.85 came from a set whose real images were all photos of people, so it overstated the detector.
- **No detector does well on edited images across both kinds of real image.** The best AUC against real photos of people was 0.79, from the model in use. Nonescape mini, Ateeqq and haywoodsloan scored 0.47, 0.35 and 0.49 there.
- **Lower cut-offs don't rescue the model in use.** Its best threshold on this set, 0.0097, catches 117 of 137 fakes but also wrongly flags 95 of 148 real images.

What these figures can't show:

- **Face swaps, video and images re-saved by social media platforms are unmeasured.**
- **Labels come from human-curated Commons categories,** so some can be wrong, and edited images may be only lightly edited.
- **Results on this set don't predict results on other kinds of image,** and no score proves that an image is authentic or false.
- **The file on disk pins Nonescape, not its publisher.** It has no published hash, so the pin records the file as downloaded on 2026-11-05.

Full results are in `data/eval/commons_licensed_2026-11-05.json`. The manifest of each file's page, licence and author stays beside the images and out of Git, because page addresses can name people.

**Older results:** `data/eval/commons_2026-11-05.json` and `data/eval/commons_recompressed_2026-11-05.json` are kept for history but no longer used. They have no real images other than people, and a downloader fault skewed that download towards small images. Both faults are now fixed.

## Limitations

- The classifier flags very few fakes at its current bands and barely beats guessing on a mixed set, as "Results from 2026-11-05" shows, so a `low` result is not reassuring. On Windows stock wallpapers it scored between 0.20 and 0.73, so mid-range scores should not be read as a signal.
- Input limits: images up to 25 MB and 50 megapixels, videos up to 200 MB. Older QuickTime files without an `ftyp` header are rejected as unsupported.
- Video analysis looks at keyframes only, up to 16 from the first 10 minutes. It does not check audio, lip sync or motion between frames.
- Video metadata covers stream properties only, not container tags.
- pHash can only match references already in the index, and a non-match says nothing about originality.
- GPS coordinates are never returned, only whether GPS data exists.
- EXIF-derived evidence text comes from the uploaded file, so the UI must escape it before display.
- JSON index lookups scan every entry, which is fine for a demo-sized index.
