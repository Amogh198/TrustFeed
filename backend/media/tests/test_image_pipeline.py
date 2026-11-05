from __future__ import annotations

import json
import sys

import pytest
from conftest import FakeClassifier, patterned_image
from PIL import Image

from backend.media import MediaConfig, analyze_media
from backend.media.errors import ClassifierUnavailable
from backend.media.models import Assessment, CheckStatus, MediaType, ModelBand
from backend.media.phash import JsonHashIndex, ReferenceEntry, compute_phash, hamming_distance


def test_image_success_is_explainable(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(0.9), config=MediaConfig())

    assert result.media_type is MediaType.IMAGE
    assert result.status is CheckStatus.COMPLETE
    assert result.score == 0.9
    assert result.checks.classifier.band is ModelBand.ELEVATED
    assert result.assessment is Assessment.SIGNALS_PRESENT
    assert len(result.sha256) == 64
    assert any("0.90" in line for line in result.evidence)
    assert any("not proof" in line for line in result.limitations)


@pytest.mark.parametrize(
    ("score", "band", "assessment"),
    [
        (0.75, ModelBand.ELEVATED, Assessment.SIGNALS_PRESENT),
        (0.74, ModelBand.INCONCLUSIVE, Assessment.INCONCLUSIVE),
        (0.26, ModelBand.INCONCLUSIVE, Assessment.INCONCLUSIVE),
        (0.25, ModelBand.LOW, Assessment.NO_STRONG_SIGNALS),
    ],
)
def test_score_bands(image_file, score, band, assessment):
    result = analyze_media(image_file, classifier=FakeClassifier(score), config=MediaConfig())
    assert result.checks.classifier.band is band
    assert result.assessment is assessment


def test_confidence_stays_null_because_scores_are_uncalibrated(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(0.99), config=MediaConfig())
    assert result.confidence is None


def test_low_score_is_never_described_as_authentic_proof(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(0.01), config=MediaConfig())
    assert "does not establish that the media is authentic" in result.summary


def test_small_image_is_inconclusive_even_with_high_score(tmp_path):
    path = tmp_path / "tiny.png"
    patterned_image(size=64).save(path)
    result = analyze_media(path, classifier=FakeClassifier(0.95), config=MediaConfig())
    assert result.score == 0.95
    assert result.assessment is Assessment.INCONCLUSIVE
    assert any("unreliable" in line for line in result.limitations)


def test_classifier_unavailable_keeps_other_evidence_and_never_invents_a_score(tmp_path):
    path = tmp_path / "sample.png"
    patterned_image().save(path)
    index = JsonHashIndex([ReferenceEntry(phash=compute_phash(Image.open(path).convert("RGB")), label="Old photo")])
    classifier = FakeClassifier(error=ClassifierUnavailable("Model weights are not available locally."))

    result = analyze_media(path, classifier=classifier, hash_index=index, config=MediaConfig())

    assert result.status is CheckStatus.UNAVAILABLE
    assert result.score is None
    assert result.checks.classifier.status is CheckStatus.UNAVAILABLE
    assert result.checks.phash.status is CheckStatus.COMPLETE
    assert result.checks.metadata.status is CheckStatus.COMPLETE
    assert any("Old photo" in line for line in result.evidence)
    assert any("weights" in line for line in result.limitations)


def test_unexpected_classifier_crash_does_not_escape(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(error=KeyError("boom")), config=MediaConfig())
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.score is None
    assert "boom" not in result.model_dump_json()


@pytest.mark.parametrize("bad", [[], [0.5, 0.5], [1.5], [-0.1], [float("nan")]])
def test_invalid_classifier_output_is_rejected(image_file, bad):
    class BadOutput(FakeClassifier):
        def predict(self, images):
            return bad

    result = analyze_media(image_file, classifier=BadOutput(), config=MediaConfig())
    assert result.score is None
    assert result.checks.classifier.status is CheckStatus.UNAVAILABLE


def test_missing_file(tmp_path):
    result = analyze_media(tmp_path / "missing.jpg", classifier=FakeClassifier(), config=MediaConfig())
    assert result.failure_code == "not_found"
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.score is None


def test_directory_is_rejected(tmp_path):
    assert analyze_media(tmp_path, classifier=FakeClassifier(), config=MediaConfig()).failure_code == "not_found"


def test_empty_file(tmp_path):
    path = tmp_path / "empty.jpg"
    path.write_bytes(b"")
    assert analyze_media(path, classifier=FakeClassifier(), config=MediaConfig()).failure_code == "empty_file"


def test_text_file_with_image_extension_is_rejected(tmp_path):
    path = tmp_path / "notes.jpg"
    path.write_text("this is not an image", encoding="utf-8")
    classifier = FakeClassifier()
    result = analyze_media(path, classifier=classifier, config=MediaConfig())
    assert result.failure_code == "unsupported_type"
    assert classifier.seen == 0


def test_type_comes_from_content_not_extension(tmp_path):
    path = tmp_path / "actually-a-png.txt"
    patterned_image().save(path, format="PNG")
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.media_type is MediaType.IMAGE
    assert result.checks.metadata.format == "PNG"


def test_truncated_jpeg_is_reported_as_corrupt(tmp_path):
    source = tmp_path / "full.jpg"
    patterned_image().save(source, format="JPEG")
    data = source.read_bytes()
    path = tmp_path / "truncated.jpg"
    path.write_bytes(data[: len(data) // 3])
    result = analyze_media(path, classifier=FakeClassifier(), config=MediaConfig())
    assert result.failure_code == "corrupt_media"
    assert result.sha256 is not None


def test_file_size_limit(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(), config=MediaConfig(max_image_bytes=10))
    assert result.failure_code == "too_large"


def test_pixel_limit(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(), config=MediaConfig(max_image_pixels=100))
    assert result.failure_code == "too_large"


def test_filename_never_appears_in_output(tmp_path):
    path = tmp_path / "private-person-name.png"
    patterned_image().save(path)
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert "private-person-name" not in result.model_dump_json()


def _exif_image(tmp_path, software="TestCam Firmware"):
    image = patterned_image()
    exif = Image.Exif()
    exif[0x010F] = "TestMake"
    exif[0x0131] = software
    exif.get_ifd(0x8769)[0x9003] = "2019:03:14 10:00:00"
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (12.0, 58.0, 41.0)
    path = tmp_path / "exif.jpg"
    image.save(path, format="JPEG", exif=exif)
    return path


def test_exif_fields_are_extracted_and_gps_is_not_exposed(tmp_path):
    result = analyze_media(_exif_image(tmp_path), classifier=FakeClassifier(0.5), config=MediaConfig())
    metadata = result.checks.metadata
    assert metadata.fields["make"] == "TestMake"
    assert metadata.fields["captured_at"] == "2019:03:14 10:00:00"
    assert metadata.has_gps is True
    dumped = result.model_dump_json()
    assert "58.0" not in dumped
    assert "41.0" not in dumped


def test_editor_tag_is_evidence_but_not_a_signal(tmp_path):
    path = _exif_image(tmp_path, software="Adobe Photoshop 25.0")
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert any("editing tool" in line for line in result.evidence)
    assert result.assessment is Assessment.INCONCLUSIVE


def test_generator_tag_is_a_signal_even_without_a_model(tmp_path):
    path = _exif_image(tmp_path, software="Stable Diffusion XL")
    classifier = FakeClassifier(error=ClassifierUnavailable("no model"))
    result = analyze_media(path, classifier=classifier, config=MediaConfig())
    assert result.assessment is Assessment.SIGNALS_PRESENT
    assert result.score is None


def test_png_generator_prompt_text_is_not_copied(tmp_path):
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("parameters", "a private prompt about someone")
    path = tmp_path / "generated.png"
    patterned_image().save(path, pnginfo=info)
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.checks.metadata.generator_hint is True
    assert "private prompt" not in result.model_dump_json()


def test_missing_exif_is_not_treated_as_a_signal(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.checks.metadata.exif_present is False
    assert result.assessment is Assessment.INCONCLUSIVE


def test_recompressed_copy_matches_within_distance(tmp_path):
    original = patterned_image(seed=7)
    copy = tmp_path / "copy.jpg"
    original.save(copy, format="JPEG", quality=40)
    index = JsonHashIndex(
        [ReferenceEntry(phash=compute_phash(original), label="2019 flood photo", first_seen="2019-08-10")]
    )
    result = analyze_media(copy, classifier=FakeClassifier(0.1), hash_index=index, config=MediaConfig())

    assert result.checks.phash.matches[0].distance <= 5
    assert result.assessment is Assessment.SIGNALS_PRESENT
    assert any("first seen 2019-08-10" in line for line in result.evidence)
    assert any("Signals disagree" in line for line in result.limitations)
    assert any("visual similarity" in line for line in result.limitations)


def test_unrelated_image_does_not_match(image_file):
    index = JsonHashIndex([ReferenceEntry(phash=compute_phash(patterned_image(seed=99)), label="Unrelated")])
    result = analyze_media(image_file, classifier=FakeClassifier(0.5), hash_index=index, config=MediaConfig())
    assert result.checks.phash.compared is True
    assert result.checks.phash.matches == []
    assert any("No perceptual match" in line for line in result.evidence)


def test_no_index_is_reported_as_no_comparison(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.checks.phash.phash is not None
    assert result.checks.phash.compared is False
    assert any("no provenance comparison" in line.casefold() for line in result.limitations)
    assert not any("No perceptual match" in line for line in result.evidence)


def test_corrupt_index_does_not_stop_analysis(image_file, tmp_path):
    bad = tmp_path / "index.json"
    bad.write_text("{not json", encoding="utf-8")
    result = analyze_media(image_file, classifier=FakeClassifier(0.5), config=MediaConfig(phash_index_path=bad))
    assert result.status is CheckStatus.COMPLETE
    assert result.checks.phash.compared is False
    assert any("could not be read" in line for line in result.limitations)


def test_malformed_index_entries_are_skipped_and_reported(image_file, tmp_path):
    path = tmp_path / "index.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {"phash": "not-a-hash", "label": "bad"},
                    {"label": "missing hash"},
                    {"phash": "0123456789abcdef", "label": "good"},
                ]
            }
        ),
        encoding="utf-8",
    )
    result = analyze_media(image_file, classifier=FakeClassifier(0.5), config=MediaConfig(phash_index_path=path))
    assert result.checks.phash.references_checked == 1
    assert any("2 malformed" in line for line in result.limitations)


def test_index_save_and_reload(tmp_path):
    path = tmp_path / "nested" / "index.json"
    index = JsonHashIndex()
    index.add(ReferenceEntry(phash="0123456789abcdef", label="Reference", source="sample"))
    index.save(path)
    loaded = JsonHashIndex.load(path)
    assert len(loaded) == 1
    assert loaded.entries[0].source == "sample"


def test_hamming_distance():
    assert hamming_distance("0000000000000000", "0000000000000003") == 2
    assert hamming_distance("ffffffffffffffff", "ffffffffffffffff") == 0


def test_missing_imagehash_keeps_pipeline_running(image_file, monkeypatch):
    monkeypatch.setitem(sys.modules, "imagehash", None)
    result = analyze_media(image_file, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.status is CheckStatus.COMPLETE
    assert result.checks.phash.status is CheckStatus.UNAVAILABLE
    assert result.score == 0.5


def test_missing_pillow_is_reported(image_file, monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    result = analyze_media(image_file, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.failure_code == "dependency_missing"
    assert result.score is None
