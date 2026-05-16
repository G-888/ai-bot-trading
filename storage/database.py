import sqlite3
import json
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = "gold_bot.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id     INTEGER PRIMARY KEY,
            first_name  TEXT,
            username    TEXT,
            ai_mode     TEXT DEFAULT 'institutional',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            direction   TEXT NOT NULL,
            price       REAL NOT NULL,
            alert_type  TEXT DEFAULT 'price',
            triggered   INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS summary_schedules (
            chat_id     INTEGER PRIMARY KEY,
            time_utc    TEXT NOT NULL,
            last_sent   TEXT
        );

        CREATE TABLE IF NOT EXISTS user_preferences (
            chat_id             INTEGER PRIMARY KEY,
            ai_mode             TEXT DEFAULT 'institutional',
            preferred_timeframe TEXT DEFAULT '1H',
            show_fib            INTEGER DEFAULT 1,
            show_smc            INTEGER DEFAULT 1,
            show_sessions       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS conversation_state (
            chat_id     INTEGER PRIMARY KEY,
            state_key   TEXT,
            state_data  TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
    _migrate_from_json()
    logger.info("Database initialised at %s", DB_PATH)


def _migrate_from_json() -> None:
    prefs_file = "user_prefs.json"
    if not os.path.exists(prefs_file):
        return
    try:
        with open(prefs_file) as f:
            data = json.load(f)
        schedules = data.get("summary_schedules", {})
        if schedules:
            with _lock, _conn() as c:
                for chat_id_str, time_utc in schedules.items():
                    c.execute(
                        "INSERT OR IGNORE INTO summary_schedules (chat_id, time_utc) VALUES (?,?)",
                        (int(chat_id_str), time_utc),
                    )
            logger.info("Migrated %d summary schedule(s) from JSON", len(schedules))
        os.rename(prefs_file, prefs_file + ".migrated")
    except Exception as e:
        logger.warning("JSON migration skipped: %s", e)


# ── Users ──────────────────────────────────────────────────────────────────────

def upsert_user(chat_id: int, first_name: str = "", username: str = "") -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO users (chat_id, first_name, username) VALUES (?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username",
            (chat_id, first_name, username),
        )


def get_user(chat_id: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        return dict(row) if row else None


def get_ai_mode(chat_id: int) -> str:
    with _lock, _conn() as c:
        row = c.execute("SELECT ai_mode FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        return row["ai_mode"] if row else "institutional"


def set_ai_mode(chat_id: int, mode: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO users (chat_id, ai_mode) VALUES (?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET ai_mode=excluded.ai_mode",
            (chat_id, mode),
        )


# ── Alerts ─────────────────────────────────────────────────────────────────────

def add_alert(chat_id: int, direction: str, price: float, alert_type: str = "price") -> int:
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO alerts (chat_id, direction, price, alert_type) VALUES (?,?,?,?)",
            (chat_id, direction, price, alert_type),
        )
        return cur.lastrowid


def get_alerts(chat_id: int) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM alerts WHERE chat_id=? AND triggered=0 ORDER BY id",
            (chat_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_active_alerts() -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM alerts WHERE triggered=0").fetchall()
        return [dict(r) for r in rows]


def mark_alert_triggered(alert_id: int) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE alerts SET triggered=1 WHERE id=?", (alert_id,))


def clear_alerts(chat_id: int) -> int:
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM alerts WHERE chat_id=? AND triggered=0", (chat_id,))
        return cur.rowcount


# ── Summary schedules ──────────────────────────────────────────────────────────

def set_summary_schedule(chat_id: int, time_utc: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO summary_schedules (chat_id, time_utc) VALUES (?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET time_utc=excluded.time_utc",
            (chat_id, time_utc),
        )


def get_summary_schedule(chat_id: int) -> str | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT time_utc FROM summary_schedules WHERE chat_id=?", (chat_id,)).fetchone()
        return row["time_utc"] if row else None


def delete_summary_schedule(chat_id: int) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM summary_schedules WHERE chat_id=?", (chat_id,))


def get_all_summary_schedules() -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM summary_schedules").fetchall()
        return [dict(r) for r in rows]


def update_summary_last_sent(chat_id: int, timestamp: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE summary_schedules SET last_sent=? WHERE chat_id=?",
            (timestamp, chat_id),
        )


def get_summary_last_sent(chat_id: int) -> str | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT last_sent FROM summary_schedules WHERE chat_id=?", (chat_id,)).fetchone()
        return row["last_sent"] if row else None


# ── User preferences ───────────────────────────────────────────────────────────

def get_preferences(chat_id: int) -> dict:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM user_preferences WHERE chat_id=?", (chat_id,)).fetchone()
        if row:
            return dict(row)
        return {
            "chat_id": chat_id,
            "ai_mode": "institutional",
            "preferred_timeframe": "1H",
            "show_fib": 1,
            "show_smc": 1,
            "show_sessions": 1,
        }


def set_preference(chat_id: int, key: str, value) -> None:
    allowed = {"ai_mode", "preferred_timeframe", "show_fib", "show_smc", "show_sessions"}
    if key not in allowed:
        raise ValueError(f"Unknown preference key: {key}")
    with _lock, _conn() as c:
        c.execute(
            f"INSERT INTO user_preferences (chat_id, {key}) VALUES (?,?) "
            f"ON CONFLICT(chat_id) DO UPDATE SET {key}=excluded.{key}",
            (chat_id, value),
        )
