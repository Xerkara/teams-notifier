"""SQLite durum kaydı (state.db): görülen dosyalar, delta bağlantıları, gönderilmiş bildirimler."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .config import data_dir

# Her öğe bir sürüm; user_version bunların sayısına eşitlenir.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE teams (
        team_id      TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        first_seen   TEXT NOT NULL,
        baselined    INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE delta_links (
        team_id    TEXT PRIMARY KEY,
        delta_link TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE files (
        team_id       TEXT NOT NULL,
        item_id       TEXT NOT NULL,
        name          TEXT NOT NULL,
        parent_path   TEXT NOT NULL DEFAULT '',
        ctag          TEXT NOT NULL DEFAULT '',
        last_modified TEXT NOT NULL DEFAULT '',
        web_url       TEXT NOT NULL DEFAULT '',
        first_seen    TEXT NOT NULL,
        PRIMARY KEY (team_id, item_id)
    );
    CREATE TABLE sent_reminders (
        assignment_id TEXT NOT NULL,
        threshold     TEXT NOT NULL,
        sent_at       TEXT NOT NULL,
        PRIMARY KEY (assignment_id, threshold)
    );
    CREATE TABLE assignments (
        assignment_id TEXT PRIMARY KEY,
        class_id      TEXT NOT NULL,
        title         TEXT NOT NULL,
        first_seen    TEXT NOT NULL
    );
    CREATE TABLE posts (
        team_id    TEXT NOT NULL,
        message_id TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        PRIMARY KEY (team_id, message_id)
    );
    """,
]


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path | str | None = None):
        self.path = str(path) if path is not None else str(data_dir() / "state.db")
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        current = self._db.execute("PRAGMA user_version").fetchone()[0]
        for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
            with self._db:
                self._db.executescript(script)
                self._db.execute(f"PRAGMA user_version = {version}")

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> State:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- meta -------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # --- teams ------------------------------------------------------------
    def upsert_team(self, team_id: str, display_name: str) -> bool:
        """Takım ilk kez görülüyorsa True döner."""
        exists = self._db.execute(
            "SELECT 1 FROM teams WHERE team_id = ?", (team_id,)
        ).fetchone()
        with self._db:
            self._db.execute(
                "INSERT INTO teams (team_id, display_name, first_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(team_id) DO UPDATE SET display_name = excluded.display_name",
                (team_id, display_name, utcnow()),
            )
        return exists is None

    def is_team_baselined(self, team_id: str) -> bool:
        row = self._db.execute(
            "SELECT baselined FROM teams WHERE team_id = ?", (team_id,)
        ).fetchone()
        return bool(row and row["baselined"])

    def mark_team_baselined(self, team_id: str) -> None:
        with self._db:
            self._db.execute("UPDATE teams SET baselined = 1 WHERE team_id = ?", (team_id,))

    def list_teams(self) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT team_id, display_name, baselined FROM teams ORDER BY display_name"
        ).fetchall()

    # --- delta ------------------------------------------------------------
    def get_delta_link(self, team_id: str) -> str | None:
        row = self._db.execute(
            "SELECT delta_link FROM delta_links WHERE team_id = ?", (team_id,)
        ).fetchone()
        return row["delta_link"] if row else None

    def set_delta_link(self, team_id: str, delta_link: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO delta_links (team_id, delta_link, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(team_id) DO UPDATE SET "
                "delta_link = excluded.delta_link, updated_at = excluded.updated_at",
                (team_id, delta_link, utcnow()),
            )

    def clear_delta_link(self, team_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM delta_links WHERE team_id = ?", (team_id,))

    # --- files ------------------------------------------------------------
    def record_file(
        self,
        team_id: str,
        item_id: str,
        *,
        name: str,
        parent_path: str = "",
        ctag: str = "",
        last_modified: str = "",
        web_url: str = "",
    ) -> str:
        """Dosyayı kaydeder. Dönen değer: 'new', 'updated' veya 'unchanged'."""
        row = self._db.execute(
            "SELECT ctag, last_modified FROM files WHERE team_id = ? AND item_id = ?",
            (team_id, item_id),
        ).fetchone()
        with self._db:
            if row is None:
                self._db.execute(
                    "INSERT INTO files (team_id, item_id, name, parent_path, ctag, "
                    "last_modified, web_url, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (team_id, item_id, name, parent_path, ctag, last_modified, web_url, utcnow()),
                )
                return "new"
            changed = row["ctag"] != ctag or row["last_modified"] != last_modified
            self._db.execute(
                "UPDATE files SET name = ?, parent_path = ?, ctag = ?, last_modified = ?, "
                "web_url = ? WHERE team_id = ? AND item_id = ?",
                (name, parent_path, ctag, last_modified, web_url, team_id, item_id),
            )
            return "updated" if changed else "unchanged"

    def peek_file(
        self, team_id: str, item_id: str, *, ctag: str = "", last_modified: str = ""
    ) -> str:
        """record_file ile aynı sınıflandırma, ama hiçbir şey yazmaz."""
        row = self._db.execute(
            "SELECT ctag, last_modified FROM files WHERE team_id = ? AND item_id = ?",
            (team_id, item_id),
        ).fetchone()
        if row is None:
            return "new"
        changed = row["ctag"] != ctag or row["last_modified"] != last_modified
        return "updated" if changed else "unchanged"

    def forget_file(self, team_id: str, item_id: str) -> None:
        with self._db:
            self._db.execute(
                "DELETE FROM files WHERE team_id = ? AND item_id = ?", (team_id, item_id)
            )

    def count_files(self, team_id: str | None = None) -> int:
        if team_id is None:
            return self._db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return self._db.execute(
            "SELECT COUNT(*) FROM files WHERE team_id = ?", (team_id,)
        ).fetchone()[0]
