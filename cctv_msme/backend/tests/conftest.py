"""Test environment: temp DB/data dir, mock LLM, numpy vector store.

Env vars MUST be set before any app module import (settings are cached).
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="factory_intel_test_")

os.environ["DATABASE_URL"] = f"sqlite:///{_TMP.replace(os.sep, '/')}/test.db"
os.environ["DATA_DIR"] = _TMP
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["VECTOR_STORE_BACKEND"] = "numpy"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["SEED_DEMO_SIM_CAMERAS"] = "0"
os.environ["LOGIN_RATE_LIMIT"] = "10000/minute"
os.environ["ENVIRONMENT"] = "test"
# Never load YOLO weights during tests: cameras default to detector off
os.environ["DETECTOR_ENABLED_DEFAULT"] = "0"
os.environ["DETECTOR_MODEL"] = "disabled"
# Never download ReID weights during tests
os.environ["REID_MODEL"] = "disabled"
