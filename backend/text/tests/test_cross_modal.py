"""Cross-modal comparison, against mocked media text until the media lane provides it."""

from backend.api.app.models import ModuleStatus
from backend.text.cross_modal import compare_channels, cross_modal_checks


def test_without_media_text_it_says_nothing_was_compared():
    report = compare_channels("Flood hit the town on 3 March 2024.", None)
    assert report.status is ModuleStatus.NOT_APPLICABLE and "media" in report.reason
    assert report.assessment is None


def test_empty_or_malformed_media_text_is_ignored():
    for extracted in ({"ocr": []}, {"ocr": "not a list"}, {"ocr": [None, 5, "  "]}, {"speech": {"a": 1}}):
        assert compare_channels("Flood hit the town on 3 March 2024.", extracted).status is ModuleStatus.NOT_APPLICABLE


def test_different_dates_between_caption_and_screen_are_noted():
    report = compare_channels("Flood hit the town on 3 March 2024.", {"ocr": ["Recorded on 12 June 2019"]})
    assert report.status is ModuleStatus.COMPLETE
    assert report.channels == ["caption", "ocr"]
    assert any(item.kind == "dates" and item.channels == ["caption", "ocr"] for item in report.conflicts)
    assert report.assessment in {"notes_only", "conflicts_found"}


def test_matching_channels_raise_nothing():
    report = compare_channels(
        "The bridge collapsed on 3 March 2024.", {"ocr": ["The bridge collapsed on 3 March 2024."], "speech": ["The bridge collapsed."]}
    )
    assert report.status is ModuleStatus.COMPLETE and report.assessment == "none_found"


def test_negation_between_caption_and_speech_is_a_conflict():
    report = compare_channels(
        "The minister resigned from the cabinet yesterday.", {"speech": ["The minister did not resign from the cabinet yesterday."]}
    )
    assert report.assessment == "conflicts_found"
    conflict = next(item for item in report.conflicts if item.kind == "negation")
    assert conflict.channels == ["caption", "speech"] and "did not" in conflict.right_quote


def test_different_figures_between_screen_and_speech_conflict_without_a_caption():
    report = compare_channels(
        None, {"ocr": ["The fire killed 50 people in the market."], "speech": ["The fire killed 200 people in the market."]}
    )
    assert report.channels == ["ocr", "speech"]
    assert any(item.kind == "figures" for item in report.conflicts)


def test_size_is_limited():
    many = [f"The storm hit on {day} March 2024." for day in range(1, 29)] * 3
    report = compare_channels("The storm hit on 1 April 2023.", {"ocr": many, "speech": many})
    assert len(report.conflicts) <= 15


def test_image_match_is_reported_as_not_run_with_the_reason():
    report = compare_channels("x y z", {"ocr": ["a b c"]})
    assert report.image_caption.status is ModuleStatus.UNAVAILABLE
    assert "safetensors" in report.image_caption.reason and "licence" in report.image_caption.reason


def test_checks_cover_both_parts_even_when_nothing_ran():
    checks = cross_modal_checks(compare_channels("A claim.", None))
    assert [check["check_id"] for check in checks] == ["text.cross_modal", "text.image_caption"]
    assert all(check["reasoning"] for check in checks)
