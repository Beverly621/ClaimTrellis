"""Vercel deployment adapter for the ClaimTrellis FastAPI application."""

import os

from fastapi import FastAPI

os.environ.setdefault("CLAIM_TRELLIS_API_DOCS_ENABLED", "false")

if not os.environ.get("DATABASE_URL"):
    os.environ.setdefault("CLAIM_TRELLIS_DATA_DIR", "/tmp/claim-trellis")

from claim_trellis.api import app as claim_trellis_app  # noqa: E402

app: FastAPI = claim_trellis_app
