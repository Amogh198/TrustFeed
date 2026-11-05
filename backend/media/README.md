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

## Limitations

- The classifier's accuracy has not been measured for this project. Recompressed media, images without faces and newer generators may be unreliable. On Windows stock wallpapers it scored between 0.20 and 0.73, so mid-range scores should not be read as a signal.
- Input limits: images up to 25 MB and 50 megapixels, videos up to 200 MB. Older QuickTime files without an `ftyp` header are rejected as unsupported.
- Video analysis looks at keyframes only, up to 16 from the first 10 minutes. It does not check audio, lip sync or motion between frames.
- Video metadata covers stream properties only, not container tags.
- pHash can only match references already in the index, and a non-match says nothing about originality.
- GPS coordinates are never returned, only whether GPS data exists.
- EXIF-derived evidence text comes from the uploaded file, so the UI must escape it before display.
- JSON index lookups scan every entry, which is fine for a demo-sized index.
