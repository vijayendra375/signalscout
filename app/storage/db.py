"""SQLite database storage for raw snapshots and historical profile persistence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config.settings import settings


class StorageDB:
    """Manages local SQLite database for snapshots and profiles."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or settings.db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS company_profiles (
                    organisation_number TEXT PRIMARY KEY,
                    legal_name TEXT,
                    updated_at TEXT,
                    profile_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT,
                    content_sha256 TEXT,
                    retrieved_at TEXT,
                    content_bytes BLOB
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS historical_claims (
                    organisation_number TEXT,
                    field TEXT,
                    value_json TEXT,
                    detected_at TEXT,
                    PRIMARY KEY (organisation_number, field)
                )
            """)

    def save_profile(self, org: str, legal_name: str, updated_at: str, profile_dict: dict[str, Any]) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO company_profiles (organisation_number, legal_name, updated_at, profile_json)
                VALUES (?, ?, ?, ?)
                """,
                (org, legal_name, updated_at, json.dumps(profile_dict, ensure_ascii=False)),
            )

    def get_profile(self, org: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT profile_json FROM company_profiles WHERE organisation_number = ?",
                (org,),
            ).fetchone()
            if row:
                return json.loads(row["profile_json"])
        return None

    def get_prior_claims(self, org: str) -> Dict[str, Any]:
        """Fetch previously observed claims for change detection."""
        claims = {}
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT field, value_json FROM historical_claims WHERE organisation_number = ?",
                (org,),
            ).fetchall()
            for r in rows:
                claims[r["field"]] = json.loads(r["value_json"])
        return claims

    def update_claims(self, org: str, claims_dict: Dict[str, Any], timestamp: str) -> None:
        with self._get_connection() as conn:
            for field, val in claims_dict.items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO historical_claims (organisation_number, field, value_json, detected_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (org, field, json.dumps(val, ensure_ascii=False), timestamp),
                )
