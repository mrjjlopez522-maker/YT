"""SQLite access layer.

Conventions:
  * columns ending in `_json` are (de)serialised automatically
  * `insert/update/get/select` build parameterised SQL from validated identifiers
  * every status change goes through `set_status`, which writes status_history
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from ..errors import ValidationError
from ..textutil import now_iso

SCHEMA_VERSION = 1
_SCHEMA_FILE = Path(__file__).with_name("schema.sql")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

PRIMARY_KEYS = {
    "channels": "channel_id", "topics": "topic_id", "research": "research_id", "research_facts": "fact_id",
    "sources": "source_id", "licenses": "license_id", "voices": "voice_id", "scripts": "script_id",
    "claims": "claim_id", "videos": "video_id", "scenes": "scene_id", "assets": "asset_id",
    "approvals": "approval_id", "uploads": "upload_id", "analytics": "snapshot_id",
    "experiments": "experiment_id", "costs": "cost_id", "revenue": "revenue_id", "errors": "error_id",
}


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValidationError(f"Invalid SQL identifier {name!r}")
    return name


def _encode(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        _ident(key)
        if key.endswith("_json") and value is not None and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        elif isinstance(value, bool):
            value = int(value)
        out[key] = value
    return out


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key, value in list(out.items()):
        if key.endswith("_json") and isinstance(value, str):
            try:
                out[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return out


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        self.conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
        cur = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if cur is None:
            self.conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                              (SCHEMA_VERSION, now_iso()))

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN")
        try:
            yield self
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # -- generic CRUD ----------------------------------------------------
    def insert(self, table: str, row: dict, *, or_replace: bool = False) -> dict:
        _ident(table)
        data = _encode(row)
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        verb = "INSERT OR REPLACE" if or_replace else "INSERT"
        self.conn.execute(f"{verb} INTO {table} ({cols}) VALUES ({marks})", list(data.values()))
        return row

    def update(self, table: str, key: Any, changes: dict) -> None:
        _ident(table)
        if not changes:
            return
        pk = PRIMARY_KEYS[table]
        data = _encode(changes)
        sets = ", ".join(f"{c} = ?" for c in data)
        cur = self.conn.execute(f"UPDATE {table} SET {sets} WHERE {pk} = ?", [*data.values(), key])
        if cur.rowcount == 0:
            raise ValidationError(f"{table} row {key!r} not found")

    def get(self, table: str, key: Any) -> dict | None:
        _ident(table)
        pk = PRIMARY_KEYS[table]
        return _decode(self.conn.execute(f"SELECT * FROM {table} WHERE {pk} = ?", (key,)).fetchone())

    def require(self, table: str, key: Any) -> dict:
        row = self.get(table, key)
        if row is None:
            raise ValidationError(f"{table} row {key!r} not found")
        return row

    def select(self, table: str, where: dict | None = None, *, order_by: str | None = None,
               limit: int | None = None) -> list[dict]:
        _ident(table)
        sql = f"SELECT * FROM {table}"
        params: list[Any] = []
        if where:
            clauses = []
            for col, val in where.items():
                _ident(col)
                if val is None:
                    clauses.append(f"{col} IS NULL")
                elif isinstance(val, (list, tuple, set)):
                    vals = list(val)
                    clauses.append(f"{col} IN ({', '.join('?' for _ in vals)})")
                    params.extend(vals)
                else:
                    clauses.append(f"{col} = ?")
                    params.append(val)
            sql += " WHERE " + " AND ".join(clauses)
        if order_by:
            col, _, direction = order_by.partition(" ")
            _ident(col)
            sql += f" ORDER BY {col} {'DESC' if direction.upper() == 'DESC' else 'ASC'}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [_decode(r) for r in self.conn.execute(sql, params).fetchall()]

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [_decode(r) for r in self.conn.execute(sql, list(params)).fetchall()]

    def scalar(self, sql: str, params: Iterable[Any] = ()):
        row = self.conn.execute(sql, list(params)).fetchone()
        return None if row is None else row[0]

    def delete(self, table: str, where: dict) -> int:
        _ident(table)
        clauses, params = [], []
        for col, val in where.items():
            clauses.append(f"{_ident(col)} = ?")
            params.append(val)
        return self.conn.execute(f"DELETE FROM {table} WHERE {' AND '.join(clauses)}", params).rowcount

    # -- status + audit ----------------------------------------------------
    def set_status(self, table: str, key: str, new_status: str, *, reason: str | None = None,
                   extra: dict | None = None) -> None:
        pk = PRIMARY_KEYS[table]
        current = self.scalar(f"SELECT status FROM {_ident(table)} WHERE {pk} = ?", (key,))
        changes = {"status": new_status, **(extra or {})}
        if "updated_at" in self._columns(table):
            changes["updated_at"] = now_iso()
        self.update(table, key, changes)
        self.insert("status_history", {"entity_type": table, "entity_id": key, "from_status": current,
                                       "to_status": new_status, "reason": reason, "created_at": now_iso()})

    def _columns(self, table: str) -> set[str]:
        return {r[1] for r in self.conn.execute(f"PRAGMA table_info({_ident(table)})").fetchall()}

    def history(self, entity_id: str) -> list[dict]:
        return self.query("SELECT * FROM status_history WHERE entity_id = ? ORDER BY id", (entity_id,))

    def record_error(self, *, stage: str, exc: BaseException, video_id: str | None = None,
                     topic_id: str | None = None, tb: str | None = None) -> str:
        from ..logging_setup import redact
        from ..textutil import new_id
        err_id = new_id("err")
        self.insert("errors", {"error_id": err_id, "stage": stage, "video_id": video_id, "topic_id": topic_id,
                               "error_type": type(exc).__name__, "message": redact(str(exc))[:4000],
                               "traceback": redact(tb) if tb else None, "created_at": now_iso()})
        return err_id
