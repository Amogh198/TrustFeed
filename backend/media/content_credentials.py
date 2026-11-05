"""Reads a file's Content Credentials (C2PA): the real signature check.

The c2pa library does the cryptography. This module decides how to run it safely and how to say what it found.
Everything a manifest says was written by whoever made the file, so it is cleaned, cut short and never logged.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from backend.media.config import MediaConfig
from backend.media.models import CheckStatus, ContentCredentialsCheck

# File names and manifest contents are never logged: uploads may be private.
logger = logging.getLogger(__name__)

T = TypeVar("T")

SIGNED = "signed"
UNSIGNED = "unsigned"
INVALID = "invalid"

ON_TRUST_LIST = "on_trust_list"
NOT_ON_TRUST_LIST = "not_on_trust_list"
NOT_CHECKED = "not_checked"

CONTENT_CHANGED = "content_changed"
# The file matches its credentials, but they break a rule of the standard, such as an expired certificate.
RULES_FAILED = "rules_failed"
CREDENTIALS_FAILED = "credentials_failed"

# A file can name a web address for its credentials, and with the library's default settings reading that file
# contacts the address. A file must never choose who TrustFeed talks to, so every route is closed, twice over for
# manifests: fetching is off, and no host is allowed. Identity assertions can also point to the web, and are not used.
_OFFLINE_CORE = {"allowed_network_hosts": [], "allow_redirects": False, "decode_identity_assertions": False}
_OFFLINE_VERIFY = {
    "verify_after_reading": True,
    "verify_timestamp_trust": False,
    "ocsp_fetch": False,
    "remote_manifest_fetch": False,
}

# Certificate usages accepted for signing, as published at https://verify.contentauthenticity.org/trust/store.cfg.
# The library's default list refuses some of them, which called real Microsoft and OpenAI signatures invalid:
# data/eval/content_credentials_2026-11-06.json has the count. This says nothing about whether a signer can be
# trusted, which only a trust list can.
_SIGNING_USAGES = "\n".join(
    (
        "1.3.6.1.5.5.7.3.4",  # Email protection
        "1.3.6.1.5.5.7.3.36",  # Document signing
        "1.3.6.1.5.5.7.3.8",  # Time stamping
        "1.3.6.1.5.5.7.3.9",  # OCSP signing
        "1.3.6.1.4.1.311.76.59.1.9",  # Microsoft C2PA signing
        "1.3.6.1.4.1.62558.2.1",  # C2PA claim signing
    )
)

# The library lists this as a failure when a signer isn't on the trust list, but the signature can still be good.
_UNTRUSTED_SIGNER = "signingCredential.untrusted"
# Real files signed properly at the time can break these rules, so they aren't treated as signs of tampering.
_RULE_FAILURES = frozenset({"signingCredential.expired", "signingCredential.invalid", "assertion.action.malformed"})
_CLAIM_SIGNATURE_GOOD = "claimSignature.validated"
_CONTENT_HASH = r"assertion\.(dataHash|bmffHash|boxesHash|collectionHash)"
_CONTENT_HASH_MATCH = re.compile(_CONTENT_HASH + r"\.match")
_CONTENT_HASH_MISMATCH = re.compile(_CONTENT_HASH + r"\.mismatch")
_SAFE_CODE = re.compile(r"[A-Za-z0-9._-]{1,80}")
_ACTIONS_LABEL = re.compile(r"c2pa\.actions(\.v\d+)?(__\d+)?")
_SOURCE_TYPE = re.compile(r"https?://cv\.iptc\.org/newscodes/digitalsourcetype/([A-Za-z]+)")
_MAX_TEXT = 80
_MAX_CODES = 10
_MAX_HISTORY = 20

# What the IPTC source types say about how media was made. Anything else in a manifest is left out.
AI_SOURCES = frozenset({"trainedAlgorithmicMedia", "compositeWithTrainedAlgorithmicMedia"})
SOURCE_MEANINGS = {
    "trainedAlgorithmicMedia": "made by a trained AI model",
    "compositeWithTrainedAlgorithmicMedia": "combined with AI-generated content",
    "algorithmicMedia": "made by an algorithm without training data",
    "algorithmicallyEnhanced": "enhanced by an algorithm",
    "dataDrivenMedia": "made by an algorithm from data",
    "digitalCapture": "captured by a camera or recorder",
    "computationalCapture": "captured with computational processing",
    "compositeCapture": "combined from several captures",
    "composite": "combined from several sources",
    "compositeSynthetic": "combined with synthetic content",
    "digitalCreation": "made by a person with digital tools",
    "digitalArt": "made by a person with digital tools",
    "humanEdits": "edited by a person",
    "minorHumanEdits": "lightly edited by a person",
    "negativeFilm": "scanned from a film negative",
    "positiveFilm": "scanned from film",
    "print": "scanned from a print",
    "screenCapture": "a screen capture",
    "virtualRecording": "a recording of a virtual scene",
}

REMOTE_REASON = (
    "The file points to Content Credentials at a web address. They were not fetched, because a file must not be able "
    "to make TrustFeed contact a site of its choosing. So whether this file is signed is unknown."
)
HISTORY_FAILED = "An earlier step in this file's history did not validate, so only the newest step is described."


def _unavailable(reason: str) -> ContentCredentialsCheck:
    return ContentCredentialsCheck(status=CheckStatus.UNAVAILABLE, limitations=[reason])


def _invalid(reason: str, codes: list[str] | None = None) -> ContentCredentialsCheck:
    """Nothing else from the manifest is kept, because it can't be tied to this file."""
    return ContentCredentialsCheck(
        status=CheckStatus.COMPLETE, state=INVALID, invalid_reason=reason, failure_codes=codes or []
    )


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean(value: object) -> str | None:
    """Keep only short, printable text. Control and direction-changing characters could disguise it on screen."""
    if not isinstance(value, str):
        return None
    text = "".join(character for character in value if character.isprintable() and character not in "<>").strip()
    return text[:_MAX_TEXT].strip() or None


def _timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _codes(items: object) -> list[str]:
    codes = [_as_dict(item).get("code") for item in _as_list(items)]
    # An unexpected code still counts as a failure, but only a well-formed one is shown.
    return [code if isinstance(code, str) and _SAFE_CODE.fullmatch(code) else "unrecognised" for code in codes]


def _claim_generator(manifest: dict[str, Any]) -> str | None:
    for entry in _as_list(manifest.get("claim_generator_info")):
        name = _clean(_as_dict(entry).get("name"))
        if name:
            return name
    return _clean(manifest.get("claim_generator"))


def _declared_sources(manifest: dict[str, Any]) -> list[str]:
    found: dict[str, None] = {}
    for assertion in _as_list(manifest.get("assertions")):
        assertion = _as_dict(assertion)
        label = assertion.get("label")
        if not (isinstance(label, str) and _ACTIONS_LABEL.fullmatch(label)):
            continue
        for action in _as_list(_as_dict(assertion.get("data")).get("actions")):
            source = _as_dict(action).get("digitalSourceType")
            matched = _SOURCE_TYPE.fullmatch(source) if isinstance(source, str) else None
            if matched and matched[1] in SOURCE_MEANINGS:
                found[matched[1]] = None
    return list(found)


def _earlier_manifests(report: dict[str, Any], newest_label: str) -> list[dict[str, Any]]:
    """Follow ingredient links back from the newest manifest. AI tools often record their declaration in an earlier one."""
    store = _as_dict(report.get("manifests"))
    seen = {newest_label}
    waiting = [_as_dict(store.get(newest_label))]
    found: list[dict[str, Any]] = []
    while waiting and len(found) < _MAX_HISTORY:
        for ingredient in _as_list(waiting.pop(0).get("ingredients")):
            label = _as_dict(ingredient).get("active_manifest")
            earlier = store.get(label) if isinstance(label, str) and label not in seen else None
            if isinstance(earlier, dict):
                seen.add(label)
                found.append(earlier)
                waiting.append(earlier)
    return found[:_MAX_HISTORY]


def _history_failed(report: dict[str, Any]) -> bool:
    deltas = _as_list(_as_dict(report.get("validation_results")).get("ingredientDeltas"))
    return any(_as_list(_as_dict(_as_dict(delta).get("validationDeltas")).get("failure")) for delta in deltas)


def _what_it_claims(report: dict[str, Any], label: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Only these fields are read, so personal names, titles and thumbnails stay out of the result."""
    signature = _as_dict(manifest.get("signature_info"))
    newest = _declared_sources(manifest)
    claims: dict[str, Any] = {
        # The library calls this "issuer", but it is the organisation in the signer's own certificate.
        "signer_organisation": _clean(signature.get("issuer")),
        "signed_at": _timestamp(signature.get("time")),
        "claim_generator": _claim_generator(manifest),
        "declared_sources": newest,
    }
    if _history_failed(report):
        claims["limitations"] = [HISTORY_FAILED]
        return claims
    earlier = [source for step in _earlier_manifests(report, label) for source in _declared_sources(step)]
    claims["declared_in_history"] = [source for source in dict.fromkeys(earlier) if source not in newest]
    return claims


def declares_ai(check: ContentCredentialsCheck) -> bool:
    return any(source in AI_SOURCES for source in [*check.declared_sources, *check.declared_in_history])


def interpret(report: dict[str, Any], *, trust_checked: bool) -> ContentCredentialsCheck:
    """Turn the library's report into signed or invalid."""
    state = report.get("validation_state")
    results = _as_dict(_as_dict(report.get("validation_results")).get("activeManifest"))
    passed = _codes(results.get("success"))
    problems = [code for code in _codes(results.get("failure")) if code != _UNTRUSTED_SIGNER]
    label = report.get("active_manifest")
    manifest = _as_dict(report.get("manifests")).get(label) if isinstance(label, str) else None
    good_state = state in ("Valid", "Trusted")

    if state == "Invalid" or (good_state and problems):
        codes = list(dict.fromkeys(problems))[:_MAX_CODES]
        if any(_CONTENT_HASH_MISMATCH.fullmatch(code) for code in problems):
            return _invalid(CONTENT_CHANGED, codes)
        tied_to_this_file = _CLAIM_SIGNATURE_GOOD in passed and any(_CONTENT_HASH_MATCH.fullmatch(code) for code in passed)
        if problems and set(problems) <= _RULE_FAILURES and tied_to_this_file and isinstance(manifest, dict):
            return ContentCredentialsCheck(
                status=CheckStatus.COMPLETE,
                state=INVALID,
                invalid_reason=RULES_FAILED,
                failure_codes=codes,
                **_what_it_claims(report, label, manifest),
            )
        return _invalid(CREDENTIALS_FAILED, codes)

    if not good_state or not isinstance(manifest, dict):
        return _unavailable("The Content Credentials library gave no clear result, so whether this file is signed is unknown.")
    if state == "Trusted":
        trust = ON_TRUST_LIST
    else:
        trust = NOT_ON_TRUST_LIST if trust_checked else NOT_CHECKED
    return ContentCredentialsCheck(
        status=CheckStatus.COMPLETE, state=SIGNED, signer_trust=trust, **_what_it_claims(report, label, manifest)
    )


def _from_error(exc: Exception, c2pa: Any) -> ContentCredentialsCheck:
    """The library reports most outcomes as errors. Its messages can hold a file's web address, so none is passed on."""
    error = c2pa.C2paError
    if isinstance(exc, error.ManifestNotFound):
        return ContentCredentialsCheck(status=CheckStatus.COMPLETE, state=UNSIGNED)
    if isinstance(exc, error.NotSupported):
        return _unavailable("The Content Credentials library can't read this file type, so whether it is signed is unknown.")
    # This outcome arrives as the base error class, so its message has to be checked too.
    if isinstance(exc, error.RemoteManifest) or str(exc).startswith("Remote"):
        return _unavailable(REMOTE_REASON)
    if isinstance(exc, (error.Verify, error.Signature, error.Decoding, error.Assertion, error.AssertionNotFound, error.Manifest)):
        return _invalid(CREDENTIALS_FAILED)
    logger.warning("Content Credentials could not be read: %s", type(exc).__name__)
    return _unavailable("The Content Credentials could not be read, so whether this file is signed is unknown.")


def _load_trust_list(config: MediaConfig) -> tuple[str | None, str | None]:
    """Check the list first, because a bad one would otherwise look like a failed signature on the upload."""
    if config.c2pa_trust_list_path is None:
        return None, None
    try:
        from cryptography import x509

        pem = config.c2pa_trust_list_path.read_bytes()
        x509.load_pem_x509_certificates(pem)
        return pem.decode("ascii"), None
    except (ImportError, OSError, ValueError) as exc:
        logger.warning("Content Credentials trust list could not be read: %s", type(exc).__name__)
        return None, "The trust list could not be read, so the signer was not checked against one."


def offline_settings(trust_list: str | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "core": deepcopy(_OFFLINE_CORE),
        "verify": {**_OFFLINE_VERIFY, "verify_trust": trust_list is not None},
        "trust": {"trust_config": _SIGNING_USAGES},
    }
    if trust_list is not None:
        settings["trust"]["trust_anchors"] = trust_list
    return settings


def _read_report(path: Path, c2pa: Any, settings: dict[str, Any]) -> dict[str, Any]:
    # A stream, so the library goes by the file's content and its messages can't contain the path.
    with c2pa.Context.from_dict(settings) as context, path.open("rb") as stream:
        with c2pa.Reader(stream, context=context) as reader:
            return json.loads(reader.json())


def _with_time_limit(task: Callable[[], T], seconds: float) -> T:
    """Stop waiting after the limit. A native call can't be cancelled, so the thread is left to finish by itself."""
    outcome: list[tuple[T | None, Exception | None]] = []

    def run() -> None:
        try:
            outcome.append((task(), None))
        except Exception as exc:
            outcome.append((None, exc))

    thread = threading.Thread(target=run, daemon=True, name="content-credentials")
    thread.start()
    thread.join(seconds)
    if not outcome:
        raise TimeoutError
    value, error = outcome[0]
    if error is not None:
        raise error
    return value  # type: ignore[return-value]


def read_credentials(path: str | Path, config: MediaConfig) -> ContentCredentialsCheck:
    """Report signed, unsigned or invalid. If that can't be told, report unavailable with the reason."""
    try:
        import c2pa
    except Exception as exc:  # Besides a missing package, its native library can fail to load.
        logger.warning("Content Credentials library unavailable: %s", type(exc).__name__)
        return _unavailable("The Content Credentials library (c2pa-python) is not available, so this was not checked.")

    trust_list, note = _load_trust_list(config)
    settings = offline_settings(trust_list)
    try:
        report = _with_time_limit(lambda: _read_report(Path(path), c2pa, settings), config.c2pa_time_limit_s)
    except TimeoutError:
        check = _unavailable(
            f"Stopped after {config.c2pa_time_limit_s:g} seconds, so whether this file is signed is unknown."
        )
    except Exception as exc:
        check = _from_error(exc, c2pa)
    else:
        check = interpret(report, trust_checked=trust_list is not None)
    if note:
        check.limitations.append(note)
    return check
