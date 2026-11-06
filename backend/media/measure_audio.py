"""Measure the two speech detectors through the app's own windowing, on openly licensed labelled audio. Files stay outside the repo; results hold no file names."""
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from huggingface_hub import HfApi, hf_hub_download
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

from backend.media.audio import AUDIO_DETECTORS, choose_windows, extract_audio
from backend.media.classifier import synthetic_class_index
from backend.media.config import MediaConfig

PER_CLASS = int(sys.argv[1]) if len(sys.argv) > 1 else 75
DATASET = "garystafford/deepfake-audio-detection"
REVISION = "fcf5344bb7f82b54b6b932291326d29750ef1e82"
CACHE = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / ".cache" / "trustfeed" / "audio_eval"
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("audio_detectors.json")
config = MediaConfig.from_env()
api = HfApi()

files = {"fake": [], "real": []}
for label in files:
    files[label] = sorted(
        item.path for item in api.list_repo_tree(DATASET, path_in_repo=label, repo_type="dataset", revision=REVISION, recursive=True)
        if getattr(item, "size", None) and item.path.lower().endswith((".wav", ".mp3", ".flac", ".ogg"))
    )
    print(label, "available", len(files[label]), flush=True)
rng = random.Random(0)
chosen = {label: rng.sample(paths, min(PER_CLASS, len(paths))) for label, paths in files.items()}

tracks = []
for label, paths in chosen.items():
    for name in paths:
        local = None
        for attempt in range(4):
            try:
                local = hf_hub_download(DATASET, name, repo_type="dataset", revision=REVISION, cache_dir=str(CACHE))
                break
            except Exception as exc:  # noqa: BLE001 - the network can drop; retry, then skip this file.
                print("retry", attempt, type(exc).__name__, flush=True)
                time.sleep(5 * (attempt + 1))
        if local is None:
            continue
        try:
            track = extract_audio(Path(local), config)
        except Exception as exc:  # noqa: BLE001
            print("skip", type(exc).__name__, flush=True)
            continue
        windows = choose_windows(track) if track else []
        if windows:
            tracks.append((label, windows, track.sample_rate))
    print(label, "ready", sum(1 for t in tracks if t[0] == label), flush=True)


def auc(pos, neg):
    pos, neg = np.asarray(pos), np.asarray(neg)
    return float(((pos[:, None] > neg).sum() + 0.5 * (pos[:, None] == neg).sum()) / (len(pos) * len(neg)))


result = {
    "dataset": DATASET,
    "dataset_revision": REVISION,
    "licence": "cc-by-4.0",
    "per_class_requested": PER_CLASS,
    "note": "One public dataset, sampled with seed 0. Mean score over up to 6 ten-second windows, as the app scores them. Does not predict results on other audio.",
    "models": [],
}
for model_id, revision in AUDIO_DETECTORS:
    extractor = AutoFeatureExtractor.from_pretrained(model_id, revision=revision, local_files_only=True)
    model = AutoModelForAudioClassification.from_pretrained(model_id, revision=revision, use_safetensors=True, local_files_only=True).eval()
    target = synthetic_class_index(model.config.id2label)
    scores = {"fake": [], "real": []}
    started = time.perf_counter()
    with torch.inference_mode():
        for done, (label, windows, rate) in enumerate(tracks, start=1):
            values = [float(torch.softmax(model(**extractor(w, sampling_rate=rate, return_tensors="pt")).logits, dim=-1)[0, target]) for w in windows]
            scores[label].append(sum(values) / len(values))
            if done % 40 == 0:
                print(model_id, done, "of", len(tracks), flush=True)
    fake, real = np.array(scores["fake"]), np.array(scores["real"])
    rng2 = np.random.default_rng(0)
    boot = [auc(fake[rng2.integers(0, len(fake), len(fake))], real[rng2.integers(0, len(real), len(real))]) for _ in range(1000)]
    entry = {
        "model": f"{model_id}@{revision}",
        "fake_n": len(fake),
        "real_n": len(real),
        "auc": round(auc(fake, real), 4),
        "auc_ci95_bootstrap": [round(float(v), 4) for v in np.percentile(boot, [2.5, 97.5])],
        "fakes_at_or_above_0.75": int((fake >= 0.75).sum()),
        "real_at_or_above_0.75": int((real >= 0.75).sum()),
        "fakes_at_or_below_0.25": int((fake <= 0.25).sum()),
        "real_at_or_below_0.25": int((real <= 0.25).sum()),
        "seconds_per_file": round((time.perf_counter() - started) / len(tracks), 2),
    }
    print(json.dumps(entry), flush=True)
    result["models"].append(entry)
    del model, extractor
OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
print("done", flush=True)
