"""SQLite state for ONE serial Modal worker mounted on ONE persistent volume.

Reservations are committed before calling the provider. Uncertain calls retain their
reservation, so crashes cannot silently reset the budget. No SQLite WAL files.
"""

import json
import sqlite3
import time
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal

UNITS_PER_EUR = 1_000_000_000


def euro_units(amount):
    return int((amount * UNITS_PER_EUR).to_integral_value(rounding=ROUND_CEILING))


def month_key(now):
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")


class State:
    def __init__(self, path, persist=lambda: None):
        # Modal lifecycle hooks and methods may run on different runtime threads;
        # the single-input worker, not thread affinity, provides serialization.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS budgets (month TEXT PRIMARY KEY, spent INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, month TEXT NOT NULL,
                reserved INTEGER NOT NULL, result TEXT, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cooldowns (user TEXT PRIMARY KEY, last REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS histories (
                conversation TEXT PRIMARY KEY, messages TEXT NOT NULL, updated REAL NOT NULL
            );
        """)
        self.db.commit()
        self.persist = persist
        self.persist()

    def history(self, conversation, now):
        row = self.db.execute(
            "SELECT messages FROM histories WHERE conversation=? AND updated>?",
            (conversation, now - 7 * 86400),
        ).fetchone()
        return json.loads(row[0]) if row else []

    def previous(self, request_id, fingerprint):
        row = self.db.execute(
            "SELECT fingerprint, result FROM requests WHERE id=?", (request_id,)
        ).fetchone()
        if not row:
            return None
        if row[0] != fingerprint:
            return {"status": "conflict", "text": "ID richiesta già usato per un altro messaggio."}
        if row[1]:
            return json.loads(row[1])
        return {"status": "pending", "text": "Richiesta già ricevuta; riprova con un nuovo ID."}

    def reserve(self, request_id, fingerprint, user, amount, settings, now):
        month = month_key(now)
        with self.db:
            self.db.execute("DELETE FROM requests WHERE created<?", (now - 35 * 86400,))
            self.db.execute("DELETE FROM cooldowns WHERE last<?", (now - 86400,))
            self.db.execute("DELETE FROM histories WHERE updated<?", (now - 7 * 86400,))
            # Bound conversation storage even for authenticated API clients using new IDs.
            self.db.execute("""DELETE FROM histories WHERE conversation IN (
                SELECT conversation FROM histories ORDER BY updated DESC LIMIT -1 OFFSET 1000
            )""")
            prior = self.previous(request_id, fingerprint)
            if prior:
                return prior
            last = self.db.execute("SELECT last FROM cooldowns WHERE user=?", (user,)).fetchone()
            if last and now - last[0] < settings.cooldown_seconds:
                return {"status": "cooldown", "text": "Aspetta qualche secondo prima di riprovare."}
            self.db.execute("INSERT OR IGNORE INTO budgets VALUES (?, 0)", (month,))
            spent = self.db.execute("SELECT spent FROM budgets WHERE month=?", (month,)).fetchone()[
                0
            ]
            if spent + amount > euro_units(settings.monthly_budget_eur):
                return {
                    "status": "budget",
                    "text": "Budget mensile esaurito. Torno il prossimo mese!",
                }
            self.db.execute("UPDATE budgets SET spent=spent+? WHERE month=?", (amount, month))
            self.db.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, NULL, ?)",
                (request_id, fingerprint, month, amount, now),
            )
            self.db.execute("INSERT OR REPLACE INTO cooldowns VALUES (?, ?)", (user, now))
        self.persist()  # Must succeed BEFORE inference, not merely at container shutdown.
        return None

    def finish(self, request_id, result, actual_units=None, conversation=None, messages=None):
        with self.db:
            month, reserved = self.db.execute(
                "SELECT month, reserved FROM requests WHERE id=?", (request_id,)
            ).fetchone()
            if actual_units is not None:
                # A price/config error never grants an artificial refund.
                self.db.execute(
                    "UPDATE budgets SET spent=spent+? WHERE month=?",
                    (actual_units - reserved, month),
                )
            self.db.execute(
                "UPDATE requests SET result=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False), request_id),
            )
            if conversation is not None:
                self.db.execute(
                    "INSERT OR REPLACE INTO histories VALUES (?, ?, ?)",
                    (conversation, json.dumps(messages, ensure_ascii=False), time.time()),
                )
        self.persist()

    def claim_delivery(self, update_id, now=None):
        now = time.time() if now is None else now
        with self.db:
            self.db.execute("DELETE FROM deliveries WHERE created<?", (now - 35 * 86400,))
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO deliveries VALUES (?, ?)", (update_id, now)
            )
        self.persist()
        return cursor.rowcount == 1

    def spent_eur(self, month):
        row = self.db.execute("SELECT spent FROM budgets WHERE month=?", (month,)).fetchone()
        return Decimal(row[0] if row else 0) / UNITS_PER_EUR
