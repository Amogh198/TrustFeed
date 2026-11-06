"""The phishing list is read from disk. No test reaches the network."""

import pytest

from backend.api.app.models import ModuleStatus
from backend.text import threat_list
from backend.text.links import investigate_link
from backend.text.threat_list import NOT_SET_UP, check_threat_list


@pytest.fixture
def saved(monkeypatch, tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# a comment naming bad.example\nhttp://bad.example/login\nhttps://hacked.example/x?id=1\n", encoding="utf-8")
    monkeypatch.setenv("THREAT_LIST_PATH", str(path))
    return path


def test_without_a_list_the_check_says_it_did_not_run(monkeypatch, tmp_path):
    monkeypatch.setenv("THREAT_LIST_PATH", str(tmp_path / "missing.txt"))
    status, signs = check_threat_list("http://bad.example/login", "bad.example", False)
    assert (status.status, status.reason, signs) == (ModuleStatus.UNAVAILABLE, NOT_SET_UP, [])


def test_an_exact_address_is_strong(saved):
    status, signs = check_threat_list("HTTP://BAD.example/login/", "bad.example", False)
    assert status.status is ModuleStatus.COMPLETE
    assert [(s.sign, s.strength) for s in signs] == [("listed_on_threat_list", "strong")]


def test_a_host_alone_is_weak_because_honest_sites_get_hacked(saved):
    _, signs = check_threat_list("https://hacked.example/other", "hacked.example", False)
    assert [(s.sign, s.strength) for s in signs] == [("host_on_threat_list", "weak")]


def test_an_official_site_is_not_marked_for_another_listed_address(saved):
    assert check_threat_list("https://hacked.example/other", "hacked.example", True)[1] == []


@pytest.mark.parametrize(("url", "host"), [("https://example.org/", "example.org"), ("https://example/", "example"), ("https://notbad.example/login", "notbad.example")])
def test_other_hosts_and_comments_do_not_match(saved, url, host):
    status, signs = check_threat_list(url, host, False)
    assert status.status is ModuleStatus.COMPLETE and signs == []
    assert status.reason and "safe" in status.reason


def test_an_analysis_shows_the_sign_and_sends_nothing(saved):
    def refuse(*_args, **_kwargs):
        raise AssertionError("An outside request was made")

    report = investigate_link("http://bad.example/login", offline_reason="No consent.", request=refuse)
    assert report.threat_lists.status is ModuleStatus.COMPLETE
    assert "listed_on_threat_list" in {s.sign for s in report.signs}
    assert report.assessment == "warning_signs_found"


def test_an_oversized_download_is_refused_and_leaves_no_file(monkeypatch, tmp_path):
    path = tmp_path / "list.txt"
    monkeypatch.setenv("THREAT_LIST_PATH", str(path))
    monkeypatch.setattr(threat_list, "_MAX_BYTES", 4)

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            return b"x" * size

    monkeypatch.setattr(threat_list.urllib.request, "urlopen", lambda *_a, **_k: Answer())
    with pytest.raises(ValueError, match="larger"):
        threat_list.download_threat_list()
    assert not path.exists()
