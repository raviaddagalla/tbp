# Signed Update Packages (Phase 4)

Updates to the platform are shipped as `.fabupdate` bundles: a zip of the
release payload plus a detached Ed25519 signature over the bundle hash.

## Key generation (one-time, keep the private key secret)

```bash
python scripts/update_bundle.py genkey --out keys/
```

## Building a release bundle

```bash
python scripts/update_bundle.py sign \
  --source backend \
  --key keys/private.pem \
  --out dist/
```

Produces `dist/backend.fabupdate` and `dist/backend.fabupdate.sig`.

## Verifying

```bash
python scripts/update_bundle.py verify \
  --bundle dist/backend.fabupdate \
  --sig dist/backend.fabupdate.sig \
  --key keys/public.pem
```

## Wiring into the platform

1. Copy `keys/public.pem` onto the server and set in the backend `.env`:

   ```
   UPDATE_PUBLIC_KEY_PATH=/etc/factory-intel/public.pem
   ```

2. Admins can verify an uploaded bundle through the API:

   ```
   POST /api/admin/updates/verify   (multipart: bundle=file, signature=text)
   ```

   - Returns `verified: true` + the zip's file list when the Ed25519
     signature matches the configured public key.
   - Returns `verified: false` with a reason otherwise.
   - With no key configured the API reports `unsigned mode`; production
     deployments should always set the key.

Signature payload format: `b64url(ed25519_sig) + "." + b64url(sha256)`.
