"""Signs files with a throwaway certificate, to test the Content Credentials check on files with known answers.

The certificates and keys are made at run time, held in memory and thrown away, so none is ever stored or committed.
A signature from one of these says nothing about anyone.
"""

from __future__ import annotations

import datetime as dt
import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

IPTC_SOURCE = "http://cv.iptc.org/newscodes/digitalsourcetype/"
EMAIL_PROTECTION = "1.3.6.1.5.5.7.3.4"


@dataclass(frozen=True)
class ThrowawaySigner:
    chain_pem: bytes
    private_key_pem: bytes
    root_pem: bytes


def _name(organisation: str, common_name: str) -> Any:
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    return x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organisation),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def make_signer(
    organisation: str = "Throwaway Test Org",
    common_name: str = "Throwaway Test Signer",
    *,
    usage_oid: str = EMAIL_PROTECTION,
    valid_for_seconds: int = 30 * 24 * 60 * 60,
) -> ThrowawaySigner:
    """Make a two-level chain, because the library refuses a self-signed signing certificate.

    The library also refuses to sign with an expired certificate, so a test can use one that expires in seconds.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    now = dt.datetime.now(dt.timezone.utc)
    root_key = ec.generate_private_key(ec.SECP256R1())
    root_name = _name("Throwaway Test Authority", "Throwaway Test Root")
    root = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(_name(organisation, common_name))
        .issuer_name(root_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(seconds=valid_for_seconds))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, False, False, False, False),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([x509.ObjectIdentifier(usage_oid)]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    return ThrowawaySigner(
        chain_pem=leaf.public_bytes(pem) + root.public_bytes(pem),
        private_key_pem=key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        root_pem=root.public_bytes(pem),
    )


def sign_bytes(
    payload: bytes,
    mime: str,
    signer: ThrowawaySigner,
    *,
    source_type: str | None = "digitalCapture",
    first_action: str = "c2pa.created",
    generator: str = "throwaway-test-tool",
    extra_assertions: Sequence[dict[str, Any]] = (),
    remote_url: str | None = None,
    embed: bool = True,
    parent: bytes | None = None,
) -> bytes:
    import c2pa

    action: dict[str, Any] = {"action": first_action}
    if source_type:
        action["digitalSourceType"] = IPTC_SOURCE + source_type
    if parent is not None:
        action["parameters"] = {"ingredientIds": ["parent-file"]}
    manifest = {
        "claim_generator_info": [{"name": generator, "version": "1"}],
        "title": "throwaway test file",
        "format": mime,
        "assertions": [{"label": "c2pa.actions.v2", "data": {"actions": [action]}}, *extra_assertions],
    }
    info = c2pa.C2paSignerInfo(c2pa.C2paSigningAlg.ES256, signer.chain_pem, signer.private_key_pem, None)
    # The library's check after signing would refuse the rule-breaking files these tests need.
    with (
        c2pa.Context.from_dict({"verify": {"verify_after_sign": False}}) as context,
        c2pa.Signer.from_info(info) as native_signer,
        c2pa.Builder(manifest, context=context) as builder,
    ):
        if remote_url:
            builder.set_remote_url(remote_url)
        if not embed:
            builder.set_no_embed()
        if parent is not None:
            ingredient = {"title": "parent", "relationship": "parentOf", "label": "parent-file"}
            builder.add_ingredient(ingredient, mime, io.BytesIO(parent))
        output = io.BytesIO()
        builder.sign(native_signer, mime, io.BytesIO(payload), output)
    return output.getvalue()
