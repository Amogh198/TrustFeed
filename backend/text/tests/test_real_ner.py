"""Run the real entity model when it has been downloaded. Skipped otherwise, and offline either way."""

import pytest

from backend.text.ner import HuggingFaceNer, weights_path

pytestmark = pytest.mark.skipif(not weights_path().exists(), reason="The NER model has not been downloaded")


def test_real_model_finds_whole_names_and_places():
    found = HuggingFaceNer().predict(["Narendra Modi visited Mumbai with Dr. A. Rao and the World Health Organization."])[0]
    by_type = {}
    for item in found:
        by_type.setdefault(item.type, set()).add(item.text)
    assert "Narendra Modi" in by_type["person"]
    assert "A. Rao" in by_type["person"]
    assert "Mumbai" in by_type["place"]
    assert "World Health Organization" in by_type["organization"]
