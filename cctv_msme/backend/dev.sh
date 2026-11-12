#!/usr/bin/env bash
# Dev server with reload scoped to app/ only (see dev.ps1 for rationale).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app
