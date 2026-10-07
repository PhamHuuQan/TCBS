
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


def db_path() -> str:
    path = os.getenv("TELEGRAM_DB_PATH", "").strip()
    if not path:
        path = "/data/tcbs_telegram.db" if os.path.isdir("/data") else "./data/tcbs_telegram.db"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(db_path(), timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _connect() as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            pending_action TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            chat_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(chat_id, ticker)
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            target REAL NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_price REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            triggered_at TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)


def upsert_user(chat_id: int, user: dict[str, Any]) -> None:
    with _connect() as con:
        con.execute("""
        INSERT INTO users(chat_id,user_id,username,first_name)
        VALUES(?,?,?,?)
        ON CONFLICT(chat_id) DO UPDATE SET
          user_id=excluded.user_id,
          username=excluded.username,
          first_name=excluded.first_name,
          updated_at=CURRENT_TIMESTAMP
        """, (chat_id, user.get("id"), user.get("username"), user.get("first_name")))


def set_pending_action(chat_id: int, action: str | None) -> None:
    with _connect() as con:
        con.execute("UPDATE users SET pending_action=?, updated_at=CURRENT_TIMESTAMP WHERE chat_id=?",
                    (action, chat_id))


def get_pending_action(chat_id: int) -> str | None:
    with _connect() as con:
        row = con.execute("SELECT pending_action FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        return row["pending_action"] if row else None


def add_watch(chat_id: int, ticker: str) -> None:
    with _connect() as con:
        con.execute("INSERT OR IGNORE INTO watchlist(chat_id,ticker) VALUES(?,?)",
                    (chat_id, ticker.upper()))


def remove_watch(chat_id: int, ticker: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM watchlist WHERE chat_id=? AND ticker=?", (chat_id, ticker.upper()))


def list_watch(chat_id: int) -> list[str]:
    with _connect() as con:
        rows = con.execute("SELECT ticker FROM watchlist WHERE chat_id=? ORDER BY ticker", (chat_id,)).fetchall()
        return [r["ticker"] for r in rows]


def add_alert(chat_id: int, ticker: str, direction: str, target: float) -> int:
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO alerts(chat_id,ticker,direction,target) VALUES(?,?,?,?)",
            (chat_id, ticker.upper(), direction, float(target)),
        )
        return int(cur.lastrowid)


def list_alerts(chat_id: int) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id,ticker,direction,target,enabled,last_price,triggered_at FROM alerts WHERE chat_id=? ORDER BY id DESC",
            (chat_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def disable_alert(alert_id: int, chat_id: int) -> None:
    with _connect() as con:
        con.execute("UPDATE alerts SET enabled=0 WHERE id=? AND chat_id=?", (alert_id, chat_id))


def active_alerts() -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id,chat_id,ticker,direction,target,last_price FROM alerts WHERE enabled=1 ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def update_alert_price(alert_id: int, price: float) -> None:
    with _connect() as con:
        con.execute("UPDATE alerts SET last_price=? WHERE id=?", (float(price), alert_id))


def trigger_alert(alert_id: int) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE alerts SET enabled=0, triggered_at=CURRENT_TIMESTAMP WHERE id=?",
            (alert_id,),
        )


def save_history(chat_id: int, role: str, content: str) -> None:
    with _connect() as con:
        con.execute("INSERT INTO chat_history(chat_id,role,content) VALUES(?,?,?)",
                    (chat_id, role, content[-12000:]))
        con.execute("""
        DELETE FROM chat_history
        WHERE chat_id=? AND id NOT IN (
            SELECT id FROM chat_history WHERE chat_id=? ORDER BY id DESC LIMIT 12
        )
        """, (chat_id, chat_id))


def recent_history(chat_id: int, limit: int = 8) -> list[dict[str, str]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT role,content FROM chat_history WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def allowed_user(chat_id: int, user_id: int) -> bool:
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if not raw:
        return False
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    return str(user_id) in allowed
