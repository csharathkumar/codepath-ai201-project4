"""
seed_db.py — Populate the audit log with sample entries for demonstration.
Run once: python seed_db.py
"""

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

DB_PATH = "provenance.db"

SAMPLES = [
    {
        "event_type": "decision",
        "content_id": "poem-001",
        "creator_id": "user_alice",
        "verdict": "human",
        "confidence": 0.18,
        "llm_score": 0.15,
        "stylo_score": 0.22,
        "label_variant": "high_human",
        "status": "decided",
        "appeal_reason": None,
        "delta_days": -3,
    },
    {
        "event_type": "decision",
        "content_id": "story-007",
        "creator_id": "user_bob",
        "verdict": "ai",
        "confidence": 0.84,
        "llm_score": 0.88,
        "stylo_score": 0.77,
        "label_variant": "high_ai",
        "status": "decided",
        "appeal_reason": None,
        "delta_days": -2,
    },
    {
        "event_type": "decision",
        "content_id": "essay-042",
        "creator_id": "user_carol",
        "verdict": "uncertain",
        "confidence": 0.51,
        "llm_score": 0.60,
        "stylo_score": 0.35,
        "label_variant": "uncertain",
        "status": "decided",
        "appeal_reason": None,
        "delta_days": -1,
    },
    {
        "event_type": "decision",
        "content_id": "flash-019",
        "creator_id": "user_dan",
        "verdict": "ai",
        "confidence": 0.79,
        "llm_score": 0.82,
        "stylo_score": 0.73,
        "label_variant": "high_ai",
        "status": "under_review",
        "appeal_reason": None,
        "delta_days": -1,
    },
    {
        "event_type": "appeal",
        "content_id": "flash-019",
        "creator_id": "user_dan",
        "verdict": None,
        "confidence": None,
        "llm_score": None,
        "stylo_score": None,
        "label_variant": None,
        "status": "under_review",
        "appeal_reason": (
            "I wrote this story entirely myself over three evenings. "
            "I sometimes write in a clean, structured style which may "
            "have triggered the AI classifier. I can provide my draft history."
        ),
        "delta_days": 0,
    },
]


def seed():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS submissions (
            content_id   TEXT PRIMARY KEY,
            creator_id   TEXT,
            status       TEXT DEFAULT 'decided',
            created_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id      TEXT UNIQUE,
            event_type    TEXT,
            content_id    TEXT,
            creator_id    TEXT,
            timestamp     TEXT,
            verdict       TEXT,
            confidence    REAL,
            llm_score     REAL,
            stylo_score   REAL,
            label_variant TEXT,
            appeal_reason TEXT,
            status        TEXT
        );
    """)

    now = datetime.now(timezone.utc)

    for s in SAMPLES:
        ts = (now + timedelta(days=s["delta_days"])).isoformat()

        # Upsert submission row
        conn.execute(
            """INSERT OR REPLACE INTO submissions (content_id, creator_id, status, created_at)
               VALUES (?, ?, ?, ?)""",
            (s["content_id"], s["creator_id"], s["status"], ts),
        )

        # Insert audit entry
        conn.execute(
            """INSERT OR IGNORE INTO audit_log
               (event_id, event_type, content_id, creator_id, timestamp,
                verdict, confidence, llm_score, stylo_score, label_variant,
                appeal_reason, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                s["event_type"],
                s["content_id"],
                s["creator_id"],
                ts,
                s["verdict"],
                s["confidence"],
                s["llm_score"],
                s["stylo_score"],
                s["label_variant"],
                s["appeal_reason"],
                s["status"],
            ),
        )

    conn.commit()
    conn.close()
    print(f"Seeded {len(SAMPLES)} audit log entries into {DB_PATH}.")


if __name__ == "__main__":
    seed()
