#!/usr/bin/env python3
"""Build and verify signed update bundles (Phase 4, roadmap item 10).

Usage:
  python scripts/update_bundle.py genkey --out keys/
  python scripts/update_bundle.py sign --source backend --key keys/private.pem --out dist/
  python scripts/update_bundle.py verify --bundle dist/backend.fabupdate --sig dist/backend.fabupdate.sig --key keys/public.pem
  python scripts/update_bundle.py verify --bundle dist/backend.fabupdate --key keys/public.pem --sig-inline

Signature scheme: Ed25519 over the SHA-256 digest of the bundle bytes.
The .sig file contains b64url(ed25519_signature) | b64url(sha256_hex).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _load_private(path: Path) -> Ed25519PrivateKey:
    return serialization.load_pem_private_key(path.read_bytes(), password=None)  # type: ignore[return-value]


def _load_public(path: Path) -> Ed25519PublicKey:
    return serialization.load_pem_public_key(path.read_bytes())  # type: ignore[return-value]


def genkey(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    (out / "private.pem").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    (out / "public.pem").write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"wrote {out / 'private.pem'} (keep secret) and {out / 'public.pem'}")


def sign(source: Path, key_path: Path, out: Path, name: str | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        bundle_name = (name or source.name) + ".fabupdate"
        bundle_path = out / bundle_name
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(source):
                for f in files:
                    full = Path(root) / f
                    arc = full.relative_to(source).as_posix()
                    zf.write(full, arc)
    else:
        bundle_path = out / ((name or source.stem) + ".fabupdate")
        bundle_path.write_bytes(source.read_bytes())

    digest = hashlib.sha256(bundle_path.read_bytes()).digest()
    key = _load_private(key_path)
    sig = key.sign(digest)
    payload = (
        base64.urlsafe_b64encode(sig).decode()
        + "."
        + base64.urlsafe_b64encode(digest).decode()
    )
    (out / (bundle_path.name + ".sig")).write_text(payload, encoding="utf-8")
    print(f"signed {bundle_path} -> {bundle_path.name}.sig")


def verify(bundle: Path, key_path: Path, sig_path: Path | None, sig_inline: str | None) -> int:
    payload = None
    if sig_path:
        payload = sig_path.read_text(encoding="utf-8").strip()
    elif sig_inline:
        payload = sig_inline
    if not payload:
        print("error: no signature provided (use --sig or --sig-inline)")
        return 2
    if "." not in payload:
        print("FAIL: malformed signature payload")
        return 1
    sig_b64, digest_b64 = payload.split(".", 1)
    try:
        sig = base64.urlsafe_b64decode(sig_b64)
        expected_digest = base64.urlsafe_b64decode(digest_b64)
    except Exception:  # noqa: BLE001
        print("FAIL: malformed signature payload")
        return 1
    actual_digest = hashlib.sha256(bundle.read_bytes()).digest()
    if actual_digest != expected_digest:
        print("FAIL: bundle hash mismatch (tampered?)")
        return 1
    pub = _load_public(key_path)
    try:
        pub.verify(sig, actual_digest)
    except Exception:  # noqa: BLE001
        print("FAIL: Ed25519 signature invalid")
        return 1
    print(f"OK: {bundle} verified (Ed25519)")
    if zipfile.is_zipfile(bundle):
        with zipfile.ZipFile(bundle) as zf:
            for info in zf.infolist():
                print(f"  {info.filename}  ({info.file_size} bytes)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("genkey")
    g.add_argument("--out", type=Path, required=True)

    s = sub.add_parser("sign")
    s.add_argument("--source", type=Path, required=True)
    s.add_argument("--key", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--name", type=str, default=None)

    v = sub.add_parser("verify")
    v.add_argument("--bundle", type=Path, required=True)
    v.add_argument("--key", type=Path, required=True)
    v.add_argument("--sig", type=Path, default=None)
    v.add_argument("--sig-inline", type=str, default=None)

    args = ap.parse_args()
    if args.cmd == "genkey":
        genkey(args.out)
        return 0
    if args.cmd == "sign":
        sign(args.source, args.key, args.out, args.name)
        return 0
    return verify(args.bundle, args.key, args.sig, args.sig_inline)


if __name__ == "__main__":
    sys.exit(main())
