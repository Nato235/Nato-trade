"""
Stockage des signaux et de l'historique d'analyse en SQLite.
"""

import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager

from . import config
from .signals import Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    asset TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    rr_ratio REAL NOT NULL,
    confirmations TEXT NOT NULL,
    high_confidence INTEGER NOT NULL,
    mode TEXT NOT NULL,
    result TEXT DEFAULT 'en_cours'
);

CREATE TABLE IF NOT EXISTS analysis_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    asset TEXT NOT NULL,
    trend_direction TEXT NOT NULL
);
"""


@contextmanager
def get_connection():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def save_signal(signal: Signal) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO signals
                (created_at, asset, timeframe, direction, entry_price, stop_loss,
                 take_profit, rr_ratio, confirmations, high_confidence, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                signal.asset,
                signal.timeframe,
                signal.direction,
                signal.entry_price,
                signal.stop_loss,
                signal.take_profit,
                signal.rr_ratio,
                ",".join(signal.confirmations),
                int(signal.high_confidence),
                signal.mode,
            ),
        )
        return cursor.lastrowid


def log_trend_analysis(asset: str, trend_direction: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO analysis_log (created_at, asset, trend_direction) VALUES (?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), asset, trend_direction),
        )


def update_signal_result(signal_id: int, result: str):
    with get_connection() as conn:
        conn.execute("UPDATE signals SET result = ? WHERE id = ?", (result, signal_id))


def get_performance_summary():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT mode, result, COUNT(*) as count FROM signals GROUP BY mode, result"
        ).fetchall()
    return [dict(row) for row in rows]
