"""
Thin MongoDB client used to write transcript status back to the
same collections the Next.js app uses (meetings + transcripts + logs).
"""
from __future__ import annotations

import logging
from pymongo import MongoClient
from pymongo.database import Database
from app.core.config import settings

_client: MongoClient | None = None

logger = logging.getLogger(__name__)


def get_db() -> Database:
    global _client
    if _client is None:
        if not settings.MONGODB_URI:
            raise RuntimeError("MONGODB_URI is not configured.")
        _client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
    return _client.get_default_database()
