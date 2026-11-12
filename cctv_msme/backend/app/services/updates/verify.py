"""Verification of signed update bundles (Phase 4).

Signature format (produced by scripts/update_bundle.py):
    b64url(ed25519_signature) + "." + b64url(sha256_hex_of_bundle_bytes)
"""
from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import get_settings


def _load_public_key(path: Path) -> Ed25519PublicKey:
    return serialization.load_pem_public_key(path.read_bytes())  # type: ignore[return-value]


def _parse_payload(payload: str) -> tuple[bytes, bytes] | None:
    try:
        sig_b64, digest_b64 = payload.strip().split(".")
        return base64.urlsafe_b64decode(sig_b64), base64.urlsafe_b64decode(digest_b64)
    except (ValueError, TypeError):
        return None


def verify_bundle(data: bytes, payload: str) -> tuple[bool, str]:
    """Verify ``data`` against a signature payload using the configured public key.

    Returns (ok, detail). When no public key is configured the bundle is
    reported as "unsigned mode" (ok=False, detail explains why).
    """
    settings = get_settings()
    key_path = Path(settings.update_public_key_path)
    if not settings.update_public_key_path.strip() or not key_path.exists():
        return False, "unsigned mode: no UPDATE_PUBLIC_KEY_PATH configured"
    parsed = _parse_payload(payload)
    if parsed is None:
        return False, "malformed signature payload"
    sig, expected_digest = parsed
    actual = hashlib.sha256(data).digest()
    if actual != expected_digest:
        return False, "bundle hash mismatch (tampered?)"
    try:
        _load_public_key(key_path).verify(sig, actual)
    except (InvalidSignature, Exception):  # noqa: BLE001
        return False, "Ed25519 signature invalid"
    return True, "signature valid"


def list_entries(data: bytes) -> list[str]:
    if not zipfile.is_zipfile(__import__("io").BytesIO(data)):
        return []
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
        return [i.filename for i in zf.infolist()]
