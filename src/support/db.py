"""数据库与仓储支撑能力。"""

import hmac
import json
from datetime import datetime, timedelta
from hashlib import sha1, sha256
from pathlib import Path
from pprint import pprint
import secrets
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .core import Activities, MemberStatsRepository, TopicRepository


_SQLITE_NOW_EXPR = "datetime('now', 'localtime')"
_SQLITE_BUSY_TIMEOUT_MS = 10000


def _hash_bot_secret(secret: str) -> str:
    return sha256(str(secret or "").encode("utf-8")).hexdigest()


class _SerializedSqliteConnection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.RLock()
        self._local = threading.local()

    def _transaction_depth(self) -> int:
        return int(getattr(self._local, "transaction_depth", 0))

    def __enter__(self):
        self._lock.acquire()
        depth = self._transaction_depth()
        try:
            if depth == 0:
                self._conn.__enter__()
            self._local.transaction_depth = depth + 1
            return self
        except Exception:
            self._lock.release()
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        depth = self._transaction_depth()
        if depth <= 0:
            raise RuntimeError("SQLite connection context exited without matching enter")
        self._local.transaction_depth = depth - 1
        try:
            if depth == 1:
                return self._conn.__exit__(exc_type, exc_val, exc_tb)
            return False
        finally:
            self._lock.release()

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._conn.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._conn.executescript(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        with self._lock:
            return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            self._conn.rollback()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def _open_sqlite_connection(
    db_path: Path,
    *,
    row_factory: Optional[Any] = None,
) -> _SerializedSqliteConnection:
    raw_conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    if row_factory is not None:
        raw_conn.row_factory = row_factory
    raw_conn.execute("PRAGMA foreign_keys = ON")
    raw_conn.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
    raw_conn.execute("PRAGMA journal_mode = WAL")
    return _SerializedSqliteConnection(raw_conn)


class GroupDatabase:
    def __new__(cls, *args, **kwargs):
        return _EmbeddedGroupDatabase(*args, **kwargs)


class InternalDatabase:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (Path("data") / "internal_api.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = _open_sqlite_connection(self.db_path, row_factory=sqlite3.Row)
        self._create_tables()

    def _create_tables(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bot_users (
                    user_id TEXT PRIMARY KEY,
                    qq_uin TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'disabled')),
                    secret TEXT NOT NULL,
                    last_login_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_bot_users_status ON bot_users (status);
                CREATE TABLE IF NOT EXISTS bot_nonce_uses (
                    bot_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    PRIMARY KEY (bot_id, nonce)
                );
                CREATE INDEX IF NOT EXISTS idx_bot_nonce_expires ON bot_nonce_uses (expires_at);
                CREATE TABLE IF NOT EXISTS bot_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES bot_users(user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_bot_sessions_user ON bot_sessions (user_id, expires_at);
                CREATE TABLE IF NOT EXISTS bot_ranks (
                    user_id TEXT PRIMARY KEY,
                    rank TEXT NOT NULL,
                    mmr INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES bot_users(user_id)
                );
                CREATE TABLE IF NOT EXISTS codex_jobs (
                    job_id TEXT PRIMARY KEY,
                    bot_self_id TEXT,
                    user_id INTEGER NOT NULL,
                    group_id INTEGER,
                    chat_type TEXT NOT NULL CHECK (chat_type IN ('private', 'group')),
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'timeout')
                    ),
                    result_text TEXT,
                    error_text TEXT,
                    command_text TEXT,
                    codex_session_id TEXT,
                    resume_mode TEXT,
                    source_message_id TEXT,
                    started_at DATETIME,
                    finished_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_codex_jobs_user_created
                    ON codex_jobs (user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_codex_jobs_status_created
                    ON codex_jobs (status, created_at DESC);
            """
            )
            user_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(bot_users)").fetchall()}
            if "secret_hash" not in user_columns:
                self.conn.execute("ALTER TABLE bot_users ADD COLUMN secret_hash TEXT NOT NULL DEFAULT ''")
            columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(codex_jobs)").fetchall()}
            if "codex_session_id" not in columns:
                self.conn.execute("ALTER TABLE codex_jobs ADD COLUMN codex_session_id TEXT")
            if "resume_mode" not in columns:
                self.conn.execute("ALTER TABLE codex_jobs ADD COLUMN resume_mode TEXT")
            self._migrate_bot_user_secrets()

    def _migrate_bot_user_secrets(self) -> None:
        rows = self.conn.execute(
            "SELECT user_id, secret, secret_hash FROM bot_users"
        ).fetchall()
        for row in rows:
            user_id = str(row["user_id"])
            legacy_secret = str(row["secret"] or "")
            secret_hash = str(row["secret_hash"] or "")

            if not secret_hash and legacy_secret:
                secret_hash = _hash_bot_secret(legacy_secret)

            if not secret_hash:
                continue

            if legacy_secret or secret_hash != str(row["secret_hash"] or ""):
                self.conn.execute(
                    """UPDATE bot_users
                    SET secret = ?, secret_hash = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?""",
                    ("", secret_hash, user_id),
                )

    def get_bot_user_by_qq(self, qq_uin: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute("SELECT * FROM bot_users WHERE qq_uin = ?", (qq_uin,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_bot_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute("SELECT * FROM bot_users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_bot_user_by_secret(self, qq_uin: str, secret: str) -> Optional[Dict[str, Any]]:
        user = self.get_bot_user_by_qq(qq_uin)
        if not user:
            return None

        stored_hash = str(user.get("secret_hash") or "")
        if not stored_hash and user.get("secret"):
            stored_hash = _hash_bot_secret(str(user["secret"]))

        provided_hash = _hash_bot_secret(secret)
        if stored_hash and hmac.compare_digest(stored_hash, provided_hash):
            return user
        return None

    def create_bot_user(
        self,
        user_id: str,
        qq_uin: str,
        display_name: Optional[str],
        status: str,
        secret: str,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO bot_users (
                    user_id, qq_uin, display_name, status, secret, secret_hash
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, qq_uin, display_name, status, "", _hash_bot_secret(secret)),
            )

    def update_bot_user_secret(self, user_id: str, secret: str) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE bot_users
                SET secret = ?, secret_hash = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?""",
                ("", _hash_bot_secret(secret), user_id),
            )

    def update_bot_user_status(self, user_id: str, status: str) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE bot_users
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?""",
                (status, user_id),
            )

    def update_bot_user_display_name(self, user_id: str, display_name: str) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE bot_users
                SET display_name = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?""",
                (display_name, user_id),
            )

    def update_bot_user_last_login(self, user_id: str) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE bot_users
                SET last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?""",
                (user_id,),
            )

    def reserve_bot_nonce(self, bot_id: str, nonce: str, expires_at: datetime) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO bot_nonce_uses (
                        bot_id, nonce, expires_at
                    ) VALUES (?, ?, ?)""",
                    (bot_id, nonce, expires_at.isoformat()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def cleanup_expired_nonces(self) -> int:
        with self.conn:
            cursor = self.conn.execute(
                f"DELETE FROM bot_nonce_uses WHERE datetime(expires_at) < {_SQLITE_NOW_EXPR}"
            )
            return cursor.rowcount

    def cleanup_expired_bot_sessions(self) -> int:
        with self.conn:
            cursor = self.conn.execute(
                f"DELETE FROM bot_sessions WHERE datetime(expires_at) < {_SQLITE_NOW_EXPR}"
            )
            return cursor.rowcount

    def create_bot_session(self, session_id: str, user_id: str, expires_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO bot_sessions (
                    session_id, user_id, expires_at
                ) VALUES (?, ?, ?)""",
                (session_id, user_id, expires_at.isoformat()),
            )

    def get_bot_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                f"""SELECT * FROM bot_sessions
                WHERE session_id = ?
                  AND datetime(expires_at) >= {_SQLITE_NOW_EXPR}""",
                (session_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_bot_session(self, session_id: str) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM bot_sessions WHERE session_id = ?",
                (session_id,),
            )
            return cursor.rowcount > 0

    def ensure_bot_rank(self, user_id: str) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO bot_ranks (
                    user_id, rank
                ) VALUES (?, ?)""",
                (user_id, "unranked"),
            )

    def get_bot_rank(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                "SELECT rank, mmr, wins, losses FROM bot_ranks WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_codex_job(
        self,
        *,
        job_id: str,
        bot_self_id: Optional[str],
        user_id: int,
        group_id: Optional[int],
        chat_type: str,
        prompt: str,
        status: str,
        command_text: str,
        codex_session_id: Optional[str],
        resume_mode: Optional[str],
        source_message_id: Optional[str],
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO codex_jobs (
                    job_id,
                    bot_self_id,
                    user_id,
                    group_id,
                    chat_type,
                    prompt,
                    status,
                    command_text,
                    codex_session_id,
                    resume_mode,
                    source_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    bot_self_id,
                    user_id,
                    group_id,
                    chat_type,
                    prompt,
                    status,
                    command_text,
                    codex_session_id,
                    resume_mode,
                    source_message_id,
                ),
            )

    def get_codex_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute("SELECT * FROM codex_jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_codex_jobs(self, *, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT * FROM codex_jobs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?""",
                (user_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_codex_session(self, *, user_id: int) -> Optional[str]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT codex_session_id FROM codex_jobs
                WHERE user_id = ?
                  AND codex_session_id IS NOT NULL
                  AND codex_session_id != ''
                ORDER BY created_at DESC
                LIMIT 1""",
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return row["codex_session_id"]

    def update_codex_job_status(
        self,
        *,
        job_id: str,
        status: str,
        result_text: Optional[str] = None,
        error_text: Optional[str] = None,
        codex_session_id: Optional[str] = None,
        resume_mode: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> bool:
        fields = ["status = ?"]
        values: List[Any] = [status]
        if result_text is not None:
            fields.append("result_text = ?")
            values.append(result_text)
        if error_text is not None:
            fields.append("error_text = ?")
            values.append(error_text)
        if codex_session_id is not None:
            fields.append("codex_session_id = ?")
            values.append(codex_session_id)
        if resume_mode is not None:
            fields.append("resume_mode = ?")
            values.append(resume_mode)
        if started_at is not None:
            fields.append("started_at = ?")
            values.append(started_at.isoformat())
        if finished_at is not None:
            fields.append("finished_at = ?")
            values.append(finished_at.isoformat())
        values.append(job_id)
        with self.conn:
            cursor = self.conn.execute(
                f"UPDATE codex_jobs SET {', '.join(fields)} WHERE job_id = ?",
                tuple(values),
            )
            return cursor.rowcount > 0

    def close(self) -> None:
        self.conn.close()


CodexInternalDatabase = InternalDatabase


class AIAssistantStateDatabase:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (Path("data") / "ai_assistant" / "assistant_state.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = _open_sqlite_connection(self.db_path, row_factory=sqlite3.Row)
        self._create_tables()

    def _create_tables(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS assistant_configs (
                    scope_type TEXT NOT NULL,
                    scope_id INTEGER NOT NULL,
                    config_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (scope_type, scope_id)
                );
                CREATE INDEX IF NOT EXISTS idx_assistant_configs_scope
                    ON assistant_configs (scope_type, scope_id);
            """
            )

    def get_config(self, scope_type: str, scope_id: int) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT config_json
                FROM assistant_configs
                WHERE scope_type = ? AND scope_id = ?""",
                (scope_type, int(scope_id)),
            )
            row = cursor.fetchone()
            if not row:
                return None
            try:
                data = json.loads(row["config_json"] or "{}")
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

    def upsert_config(self, scope_type: str, scope_id: int, config: Dict[str, Any]) -> None:
        payload = json.dumps(config or {}, ensure_ascii=False)
        with self.conn:
            self.conn.execute(
                """INSERT INTO assistant_configs (
                    scope_type, scope_id, config_json
                ) VALUES (?, ?, ?)
                ON CONFLICT(scope_type, scope_id) DO UPDATE SET
                    config_json = excluded.config_json,
                    updated_at = CURRENT_TIMESTAMP""",
                (scope_type, int(scope_id), payload),
            )

    def close(self) -> None:
        self.conn.close()


class SqliteMemberStatsRepository(MemberStatsRepository):
    def __init__(self, db: GroupDatabase):
        self.db = db

    def update_member_stats(self, member_id: int, action: Activities) -> None:
        self.db.update_member_stats(member_id, action)


class SqliteTopicRepository(TopicRepository):
    def __init__(self, db: GroupDatabase):
        self.db = db

    def add_topic(self, proposer_id: int, content: str) -> int:
        return self.db.add_topic(proposer_id, content)

    def record_supporters(self, topic_id: int, supporter_ids: List[int]) -> None:
        self.db.record_topic_supporters(topic_id, supporter_ids)

    def get_all_topics(self) -> List[Dict[str, Any]]:
        return self.db.get_all_topics()

class _EmbeddedGroupDatabase:
    def __init__(self, group_id: int, data_root: Optional[Path] = None):
        self.group_id = group_id
        root = data_root or Path("data")
        self.db_path = root / "group_management" / str(group_id) / "group_data.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = _open_sqlite_connection(self.db_path)
        self._create_tables()
        self._migrate_schema()

    def _create_tables(self):
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS members (
                    member_id INTEGER PRIMARY KEY,
                    created_topics INTEGER DEFAULT 0,
                    created_activities INTEGER DEFAULT 0,
                    voted_topics INTEGER DEFAULT 0,
                    joined_activities INTEGER DEFAULT 0,
                    published_works INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS activities (
                    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time DATETIME NOT NULL,
                    end_time DATETIME NOT NULL,
                    activity_name TEXT NOT NULL,
                    requirement TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reward TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('draft', 'active', 'ended', 'cancelled')),
                    creator_id INTEGER REFERENCES members(member_id)
                );
                CREATE TABLE IF NOT EXISTS topics (
                    topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    proposer_id INTEGER NOT NULL REFERENCES members(member_id),
                    created_time DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS service_configs (
                    service_name TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS service_state_entries (
                    service_name TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    entry_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (service_name, scope, entry_key)
                );
                CREATE INDEX IF NOT EXISTS idx_service_state_entries_service_scope
                    ON service_state_entries (service_name, scope, updated_at);
                CREATE TABLE IF NOT EXISTS scheduled_tool_jobs (
                    job_id TEXT PRIMARY KEY,
                    group_id INTEGER NOT NULL,
                    creator_user_id INTEGER NOT NULL,
                    task_name TEXT NOT NULL,
                    task_id TEXT NOT NULL UNIQUE,
                    callback_id TEXT NOT NULL UNIQUE,
                    task_type TEXT NOT NULL
                        CHECK (task_type IN ('daily', 'weekly', 'once')),
                    schedule TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_args_json TEXT NOT NULL DEFAULT '{}',
                    context_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    description TEXT NOT NULL DEFAULT '',
                    delivery_mode TEXT NOT NULL DEFAULT 'render_message',
                    risk_level TEXT NOT NULL DEFAULT 'normal',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_at DATETIME,
                    last_status TEXT,
                    last_result_json TEXT,
                    last_error TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_scheduled_tool_jobs_group_enabled
                    ON scheduled_tool_jobs (group_id, enabled, updated_at);
                CREATE INDEX IF NOT EXISTS idx_scheduled_tool_jobs_tool_name
                    ON scheduled_tool_jobs (tool_name, updated_at);
                CREATE TABLE IF NOT EXISTS scheduled_tool_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('succeeded', 'failed')),
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (job_id) REFERENCES scheduled_tool_jobs(job_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_scheduled_tool_runs_job_created
                    ON scheduled_tool_runs (job_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS engagement_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    domain_type TEXT NOT NULL CHECK (domain_type IN ('topic', 'activity')),
                    subject_id TEXT NOT NULL,
                    actor_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    related_user_id INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_engagement_events_domain_subject
                    ON engagement_events (domain_type, subject_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_engagement_events_actor
                    ON engagement_events (actor_id, created_at);
                CREATE TABLE IF NOT EXISTS points_ledger (
                    ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    ref_type TEXT,
                    ref_id TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_points_ledger_user_currency_created
                    ON points_ledger (user_id, currency, created_at);
                CREATE TABLE IF NOT EXISTS sign_in_records (
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    sign_date TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, user_id, sign_date)
                );
                CREATE TABLE IF NOT EXISTS topic_create_requests (
                    group_id INTEGER NOT NULL,
                    request_key TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    topic_id INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS idx_topic_create_requests_user
                    ON topic_create_requests (user_id, created_at);
                CREATE TABLE IF NOT EXISTS topic_votes (
                    group_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    choice INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, topic_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_topic_votes_topic
                    ON topic_votes (topic_id, created_at);
                CREATE TABLE IF NOT EXISTS applicants (
                    user_id INTEGER PRIMARY KEY,
                    error_count INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS participants (
                    user_id INTEGER NOT NULL,
                    activity_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, activity_id),
                    FOREIGN KEY (user_id) REFERENCES members(member_id),
                    FOREIGN KEY (activity_id) REFERENCES activities(activity_id)
                );
                CREATE TABLE IF NOT EXISTS activity_memberships (
                    activity_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'left', 'removed')),
                    joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    left_at DATETIME,
                    PRIMARY KEY (activity_id, user_id),
                    FOREIGN KEY (activity_id) REFERENCES activities(activity_id),
                    FOREIGN KEY (user_id) REFERENCES members(member_id)
                );
                CREATE INDEX IF NOT EXISTS idx_activity_memberships_user_status
                    ON activity_memberships (user_id, status, joined_at);
                CREATE INDEX IF NOT EXISTS idx_activity_memberships_activity_status
                    ON activity_memberships (activity_id, status, joined_at);
                CREATE TABLE IF NOT EXISTS activity_applications (
                    application_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_id INTEGER NOT NULL,
                    activity_name TEXT NOT NULL,
                    requirement TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reward TEXT NOT NULL,
                    duration INTEGER NOT NULL,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status INTEGER DEFAULT 0,
                    FOREIGN KEY (creator_id) REFERENCES members(member_id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_key TEXT PRIMARY KEY,
                    flow TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    owner_id INTEGER,
                    version INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);
                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    session_key TEXT,
                    result TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_audit_logs_group_id ON audit_logs (group_id, created_at);
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    actor_id INTEGER,
                    action TEXT NOT NULL,
                    subject_type TEXT,
                    subject_id TEXT,
                    session_key TEXT,
                    result TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_audit_events_group_id ON audit_events (group_id, created_at);
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idem_key TEXT PRIMARY KEY,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    session_key TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS vote_records (
                    session_key TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    option_idx INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_key, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_vote_records_session_key ON vote_records (session_key);
                CREATE TABLE IF NOT EXISTS member_profiles (
                    user_id INTEGER PRIMARY KEY,
                    nickname TEXT NOT NULL DEFAULT '',
                    card TEXT NOT NULL DEFAULT '',
                    role_code TEXT NOT NULL DEFAULT 'member',
                    title TEXT NOT NULL DEFAULT '',
                    join_time INTEGER,
                    last_sent_time INTEGER,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES members(member_id)
                );
                CREATE INDEX IF NOT EXISTS idx_member_profiles_role_code
                    ON member_profiles (role_code, updated_at);
                CREATE TABLE IF NOT EXISTS governance_roles (
                    user_id INTEGER NOT NULL,
                    role_code TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'revoked')),
                    source TEXT NOT NULL DEFAULT 'manual',
                    operator_id INTEGER,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    revoked_at DATETIME,
                    PRIMARY KEY (user_id, role_code),
                    FOREIGN KEY (user_id) REFERENCES members(member_id),
                    FOREIGN KEY (operator_id) REFERENCES members(member_id)
                );
                CREATE INDEX IF NOT EXISTS idx_governance_roles_role_status
                    ON governance_roles (role_code, status, updated_at);
                CREATE TABLE IF NOT EXISTS governance_cases (
                    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    proposer_id INTEGER NOT NULL,
                    target_user_id INTEGER,
                    status TEXT NOT NULL
                        CHECK (
                            status IN (
                                'supporting',
                                'nomination_publicity',
                                'statement_and_questioning',
                                'response_window',
                                'cooling',
                                'active',
                                'voting',
                                'runoff_voting',
                                'approved',
                                'rejected',
                                'cancelled'
                            )
                        ),
                    phase TEXT NOT NULL DEFAULT 'draft',
                    support_threshold INTEGER NOT NULL DEFAULT 0,
                    vote_duration_seconds INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    cooldown_until DATETIME,
                    vote_started_at DATETIME,
                    vote_ends_at DATETIME,
                    resolved_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (proposer_id) REFERENCES members(member_id),
                    FOREIGN KEY (target_user_id) REFERENCES members(member_id)
                );
                CREATE INDEX IF NOT EXISTS idx_governance_cases_status_created
                    ON governance_cases (status, created_at);
                CREATE TABLE IF NOT EXISTS governance_case_supporters (
                    case_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (case_id, user_id),
                    FOREIGN KEY (case_id) REFERENCES governance_cases(case_id),
                    FOREIGN KEY (user_id) REFERENCES members(member_id)
                );
                CREATE INDEX IF NOT EXISTS idx_governance_case_supporters_case
                    ON governance_case_supporters (case_id, created_at);
                CREATE TABLE IF NOT EXISTS governance_case_votes (
                    case_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    choice INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (case_id, user_id, choice),
                    FOREIGN KEY (case_id) REFERENCES governance_cases(case_id),
                    FOREIGN KEY (user_id) REFERENCES members(member_id)
                );
                CREATE INDEX IF NOT EXISTS idx_governance_case_votes_case
                    ON governance_case_votes (case_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_governance_case_votes_case_user
                    ON governance_case_votes (case_id, user_id, created_at);
                CREATE TABLE IF NOT EXISTS governance_freeze_locks (
                    lock_key TEXT PRIMARY KEY,
                    lock_type TEXT NOT NULL,
                    target_user_id INTEGER,
                    source_case_id INTEGER,
                    reason TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    released_at DATETIME,
                    FOREIGN KEY (target_user_id) REFERENCES members(member_id),
                    FOREIGN KEY (source_case_id) REFERENCES governance_cases(case_id)
                );
                CREATE INDEX IF NOT EXISTS idx_governance_freeze_locks_type_active
                    ON governance_freeze_locks (lock_type, active, created_at);
                CREATE INDEX IF NOT EXISTS idx_activity_time ON activities (start_time, end_time);
                CREATE INDEX IF NOT EXISTS idx_activity_id ON participants (activity_id);
                CREATE INDEX IF NOT EXISTS idx_participants_user_id ON participants (user_id);
                CREATE INDEX IF NOT EXISTS idx_topics_proposer_id ON topics (proposer_id);
                CREATE INDEX IF NOT EXISTS idx_activities_creator_id ON activities (creator_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_owner_status_expires ON sessions (owner_id, status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_audit_events_session_created ON audit_events (session_key, created_at);
            """
            )

    def add_member(self, member_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO members (member_id) VALUES (?)",
                (member_id,),
            )

    def get_service_config(self, service_name: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT config_json
                FROM service_configs
                WHERE service_name = ?""",
                (service_name,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            try:
                data = json.loads(row[0] or "{}")
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

    def upsert_service_config(self, service_name: str, config: Dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO service_configs (
                    service_name, config_json
                ) VALUES (?, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    config_json = excluded.config_json,
                    updated_at = CURRENT_TIMESTAMP""",
                (
                    service_name,
                    json.dumps(config or {}, ensure_ascii=False),
                ),
            )

    def get_service_state_entry(
        self,
        service_name: str,
        scope: str,
        entry_key: str,
    ) -> Optional[Any]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT value_json
                FROM service_state_entries
                WHERE service_name = ? AND scope = ? AND entry_key = ?""",
                (service_name, scope, entry_key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None

    def upsert_service_state_entry(
        self,
        service_name: str,
        scope: str,
        entry_key: str,
        value: Any,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO service_state_entries (
                    service_name, scope, entry_key, value_json
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(service_name, scope, entry_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP""",
                (
                    service_name,
                    scope,
                    entry_key,
                    json.dumps(value, ensure_ascii=False),
                ),
            )

    def delete_service_state_entry(
        self,
        service_name: str,
        scope: str,
        entry_key: str,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """DELETE FROM service_state_entries
                WHERE service_name = ? AND scope = ? AND entry_key = ?""",
                (service_name, scope, entry_key),
            )

    def list_service_state_entries(
        self,
        service_name: str,
        scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = (
            "SELECT scope, entry_key, value_json, created_at, updated_at "
            "FROM service_state_entries WHERE service_name = ?"
        )
        params: List[Any] = [service_name]
        if scope is not None:
            query += " AND scope = ?"
            params.append(scope)
        query += " ORDER BY scope, entry_key"

        with self.conn:
            cursor = self.conn.execute(query, tuple(params))
            rows = cursor.fetchall()

        entries: List[Dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row[2])
            except json.JSONDecodeError:
                value = None
            entries.append(
                {
                    "scope": row[0],
                    "entry_key": row[1],
                    "value": value,
                    "created_at": row[3],
                    "updated_at": row[4],
                }
            )
        return entries

    def get_scheduled_tool_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT
                    job_id,
                    group_id,
                    creator_user_id,
                    task_name,
                    task_id,
                    callback_id,
                    task_type,
                    schedule,
                    tool_name,
                    tool_args_json,
                    context_snapshot_json,
                    description,
                    delivery_mode,
                    risk_level,
                    enabled,
                    last_run_at,
                    last_status,
                    last_result_json,
                    last_error,
                    created_at,
                    updated_at
                FROM scheduled_tool_jobs
                WHERE job_id = ?""",
                (job_id,),
            )
            row = cursor.fetchone()
        return self._decode_scheduled_tool_job_row(row)

    def get_scheduled_tool_job_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT
                    job_id,
                    group_id,
                    creator_user_id,
                    task_name,
                    task_id,
                    callback_id,
                    task_type,
                    schedule,
                    tool_name,
                    tool_args_json,
                    context_snapshot_json,
                    description,
                    delivery_mode,
                    risk_level,
                    enabled,
                    last_run_at,
                    last_status,
                    last_result_json,
                    last_error,
                    created_at,
                    updated_at
                FROM scheduled_tool_jobs
                WHERE task_id = ?""",
                (task_id,),
            )
            row = cursor.fetchone()
        return self._decode_scheduled_tool_job_row(row)

    def upsert_scheduled_tool_job(
        self,
        *,
        job_id: str,
        creator_user_id: int,
        task_name: str,
        task_id: str,
        callback_id: str,
        task_type: str,
        schedule: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        context_snapshot: Dict[str, Any],
        description: str,
        delivery_mode: str,
        risk_level: str,
        enabled: bool = True,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO scheduled_tool_jobs (
                    job_id,
                    group_id,
                    creator_user_id,
                    task_name,
                    task_id,
                    callback_id,
                    task_type,
                    schedule,
                    tool_name,
                    tool_args_json,
                    context_snapshot_json,
                    description,
                    delivery_mode,
                    risk_level,
                    enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    creator_user_id = excluded.creator_user_id,
                    task_name = excluded.task_name,
                    task_id = excluded.task_id,
                    callback_id = excluded.callback_id,
                    task_type = excluded.task_type,
                    schedule = excluded.schedule,
                    tool_name = excluded.tool_name,
                    tool_args_json = excluded.tool_args_json,
                    context_snapshot_json = excluded.context_snapshot_json,
                    description = excluded.description,
                    delivery_mode = excluded.delivery_mode,
                    risk_level = excluded.risk_level,
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP""",
                (
                    job_id,
                    self.group_id,
                    int(creator_user_id),
                    str(task_name),
                    str(task_id),
                    str(callback_id),
                    str(task_type),
                    str(schedule),
                    str(tool_name),
                    json.dumps(tool_args or {}, ensure_ascii=False),
                    json.dumps(context_snapshot or {}, ensure_ascii=False),
                    str(description or ""),
                    str(delivery_mode or "render_message"),
                    str(risk_level or "normal"),
                    1 if enabled else 0,
                ),
            )

    def set_scheduled_tool_job_enabled(self, job_id: str, enabled: bool) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                """UPDATE scheduled_tool_jobs
                SET enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?""",
                (1 if enabled else 0, job_id),
            )
            return cursor.rowcount > 0

    def delete_scheduled_tool_job(self, job_id: str) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM scheduled_tool_jobs WHERE job_id = ?",
                (job_id,),
            )
            return cursor.rowcount > 0

    def list_scheduled_tool_jobs(
        self,
        *,
        group_id: Optional[int] = None,
        include_disabled: bool = True,
    ) -> List[Dict[str, Any]]:
        query = (
            """SELECT
                job_id,
                group_id,
                creator_user_id,
                task_name,
                task_id,
                callback_id,
                task_type,
                schedule,
                tool_name,
                tool_args_json,
                context_snapshot_json,
                description,
                delivery_mode,
                risk_level,
                enabled,
                last_run_at,
                last_status,
                last_result_json,
                last_error,
                created_at,
                updated_at
            FROM scheduled_tool_jobs
            WHERE group_id = ?"""
        )
        params: List[Any] = [int(group_id if group_id is not None else self.group_id)]
        if not include_disabled:
            query += " AND enabled = 1"
        query += " ORDER BY updated_at DESC, created_at DESC"

        with self.conn:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [job for job in (self._decode_scheduled_tool_job_row(row) for row in rows) if job]

    def record_scheduled_tool_run(
        self,
        *,
        job_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error_text: str = "",
    ) -> None:
        normalized_result = result or {}
        with self.conn:
            self.conn.execute(
                """INSERT INTO scheduled_tool_runs (
                    job_id, status, result_json, error_text
                ) VALUES (?, ?, ?, ?)""",
                (
                    job_id,
                    status,
                    json.dumps(normalized_result, ensure_ascii=False),
                    str(error_text or ""),
                ),
            )
            self.conn.execute(
                """UPDATE scheduled_tool_jobs
                SET last_run_at = CURRENT_TIMESTAMP,
                    last_status = ?,
                    last_result_json = ?,
                    last_error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?""",
                (
                    status,
                    json.dumps(normalized_result, ensure_ascii=False),
                    str(error_text or ""),
                    job_id,
                ),
            )

    def _decode_scheduled_tool_job_row(self, row: Any) -> Optional[Dict[str, Any]]:
        if not row:
            return None

        def _load_json(value: Any) -> Any:
            try:
                return json.loads(value or "{}")
            except json.JSONDecodeError:
                return {}

        return {
            "job_id": row[0],
            "group_id": int(row[1]),
            "creator_user_id": int(row[2]),
            "task_name": row[3],
            "task_id": row[4],
            "callback_id": row[5],
            "task_type": row[6],
            "schedule": row[7],
            "tool_name": row[8],
            "tool_args": _load_json(row[9]),
            "context_snapshot": _load_json(row[10]),
            "description": row[11],
            "delivery_mode": row[12],
            "risk_level": row[13],
            "enabled": bool(row[14]),
            "last_run_at": row[15] or "",
            "last_status": row[16] or "",
            "last_result": _load_json(row[17]),
            "last_error": row[18] or "",
            "created_at": row[19],
            "updated_at": row[20],
        }

    def record_engagement_event(
        self,
        *,
        domain_type: str,
        subject_id: str,
        actor_id: int,
        action: str,
        related_user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO engagement_events (
                    group_id,
                    domain_type,
                    subject_id,
                    actor_id,
                    action,
                    related_user_id,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.group_id,
                    domain_type,
                    str(subject_id),
                    int(actor_id),
                    action,
                    int(related_user_id) if related_user_id is not None else None,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )

    def record_topic_supporters(self, topic_id: int, supporter_ids: List[int]) -> None:
        for supporter_id in supporter_ids:
            self.add_member(int(supporter_id))
            self.record_engagement_event(
                domain_type="topic",
                subject_id=str(topic_id),
                actor_id=int(supporter_id),
                action="participated",
                metadata={"source": "topic_approval"},
            )

    def _activate_activity_membership(self, user_id: int, activity_id: int) -> bool:
        cursor = self.conn.execute(
            """SELECT status
            FROM activity_memberships
            WHERE activity_id = ? AND user_id = ?""",
            (activity_id, user_id),
        )
        row = cursor.fetchone()
        if row and row[0] == "active":
            return False
        if row:
            self.conn.execute(
                """UPDATE activity_memberships
                SET status = 'active', joined_at = CURRENT_TIMESTAMP, left_at = NULL
                WHERE activity_id = ? AND user_id = ?""",
                (activity_id, user_id),
            )
        else:
            self.conn.execute(
                """INSERT INTO activity_memberships (
                    activity_id, user_id, status
                ) VALUES (?, ?, 'active')""",
                (activity_id, user_id),
            )
        return True

    def add_participant(self, user_id: int, activity_id: int) -> Tuple[bool, str]:
        self.add_member(user_id)
        activity = self.get_activity_by_activity_id(activity_id)
        if not activity:
            return False, "⛔ 该活动不存在"
        if activity.get("status") != "active":
            return False, "⛔ 活动未处于进行状态"
        with self.conn:
            if not self._activate_activity_membership(user_id, activity_id):
                return False, "您已在活动中"
            self.update_member_stats(user_id, Activities.JOINED_ACTIVITIES)
            self.record_engagement_event(
                domain_type="activity",
                subject_id=str(activity_id),
                actor_id=int(user_id),
                action="joined",
            )
            return True, ""

    def get_activities_by_uid(self, user_id: int) -> Optional[int]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT activity_memberships.activity_id
                FROM activity_memberships
                JOIN activities ON activity_memberships.activity_id = activities.activity_id
                WHERE activity_memberships.user_id = ?
                    AND activity_memberships.status = 'active'
                    AND activities.status = 'active'
                    AND strftime('%Y-%m-%dT%H:%M:%f', datetime('now', 'localtime'))
                        BETWEEN start_time AND end_time
                ORDER BY activity_memberships.activity_id DESC""",
                (user_id,),
            )
            result = cursor.fetchone()
            return result[0] if result else None

    def get_all_topics(self) -> List[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT
                    t.topic_id,
                    t.content,
                    t.proposer_id,
                    t.created_time,
                    m.created_topics AS proposer_topic_count
                FROM topics t
                LEFT JOIN members m ON t.proposer_id = m.member_id
                ORDER BY t.created_time DESC"""
            )
            topics = []
            columns = [column[0] for column in cursor.description]
            for row in cursor.fetchall():
                topic = dict(zip(columns, row))
                if topic.get("created_time"):
                    topic["created_time"] = datetime.fromisoformat(topic["created_time"]).strftime("%Y-%m-%d %H:%M:%S")
                topics.append(topic)
            return topics

    def get_participants_by_activity_id(self, activity_id: int) -> List[int]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT user_id
                FROM activity_memberships
                WHERE activity_id = ? AND status = 'active'
                ORDER BY joined_at ASC, user_id ASC""",
                (activity_id,),
            )
            return [row[0] for row in cursor]

    def add_activity(
        self,
        creator_id: int,
        activity_name: str,
        requirement: str,
        content: str,
        reward: str,
        start: datetime,
        end: datetime,
        status: str = "active",
        source_application_id: Optional[int] = None,
    ) -> int:
        self.add_member(creator_id)
        with self.conn:
            cursor = self.conn.execute(
                """INSERT INTO activities (
                    creator_id, activity_name, requirement,
                    content, reward, start_time, end_time, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (creator_id, activity_name, requirement, content, reward, start.isoformat(), end.isoformat(), status),
            )
            activity_id = int(cursor.lastrowid)
            self._activate_activity_membership(creator_id, activity_id)
            self.update_member_stats(creator_id, Activities.CREATED_ACTIVITIES)
            self.update_member_stats(creator_id, Activities.JOINED_ACTIVITIES)
            self.record_engagement_event(
                domain_type="activity",
                subject_id=str(activity_id),
                actor_id=int(creator_id),
                action="created",
                metadata={
                    "activity_name": activity_name,
                    "status": status,
                    "source_application_id": source_application_id,
                },
            )
            self.record_engagement_event(
                domain_type="activity",
                subject_id=str(activity_id),
                actor_id=int(creator_id),
                action="joined",
                metadata={"auto_join": True},
            )
            return activity_id

    def get_activity_by_activity_id(self, activity_id: int) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                "SELECT * FROM activities WHERE activity_id = ?",
                (activity_id,),
            )
            row = cursor.fetchone()
            if row:
                columns = [column[0] for column in cursor.description]
                return dict(zip(columns, row))
            return None

    def add_topic(self, proposer_id: int, content: str) -> int:
        self.add_member(proposer_id)
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO topics (proposer_id, content) VALUES (?, ?)",
                (proposer_id, content),
            )
            topic_id = int(cursor.lastrowid)
            self.update_member_stats(proposer_id, Activities.CREATED_TOPICS)
            self.record_engagement_event(
                domain_type="topic",
                subject_id=str(topic_id),
                actor_id=int(proposer_id),
                action="created",
                metadata={"content": content},
            )
            return topic_id

    def insert_ledger(
        self,
        *,
        user_id: int,
        currency: str,
        delta: int,
        reason: str,
        idempotency_key: str,
        ref_type: Optional[str] = None,
        ref_id: Optional[str] = None,
    ) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO points_ledger (
                        group_id,
                        user_id,
                        currency,
                        delta,
                        reason,
                        ref_type,
                        ref_id,
                        idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self.group_id,
                        user_id,
                        currency,
                        delta,
                        reason,
                        ref_type,
                        ref_id,
                        idempotency_key,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_balance(self, *, user_id: int, currency: str) -> int:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT COALESCE(SUM(delta), 0)
                FROM points_ledger
                WHERE group_id = ? AND user_id = ? AND currency = ?""",
                (self.group_id, user_id, currency),
            )
            row = cursor.fetchone()
            return int(row[0] or 0)

    def apply_points_cost(
        self,
        *,
        user_id: int,
        cost_points: int,
        reason: str,
        idempotency_key: str,
        ref_type: Optional[str] = None,
        ref_id: Optional[str] = None,
    ) -> Tuple[bool, int, bool]:
        normalized_cost = max(0, int(cost_points or 0))
        if normalized_cost <= 0:
            balance = self.get_balance(user_id=user_id, currency="points")
            return True, balance, False

        with self.conn:
            existing = self.conn.execute(
                """SELECT 1
                FROM points_ledger
                WHERE idempotency_key = ?""",
                (idempotency_key,),
            ).fetchone()
            if existing:
                balance = self.get_balance(user_id=user_id, currency="points")
                return True, balance, True

            balance_row = self.conn.execute(
                """SELECT COALESCE(SUM(delta), 0)
                FROM points_ledger
                WHERE group_id = ? AND user_id = ? AND currency = 'points'""",
                (self.group_id, user_id),
            ).fetchone()
            balance = int(balance_row[0] or 0)
            if balance < normalized_cost:
                return False, balance, False

            self.conn.execute(
                """INSERT INTO points_ledger (
                    group_id,
                    user_id,
                    currency,
                    delta,
                    reason,
                    ref_type,
                    ref_id,
                    idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.group_id,
                    user_id,
                    "points",
                    -normalized_cost,
                    reason,
                    ref_type,
                    ref_id,
                    idempotency_key,
                ),
            )

        new_balance = self.get_balance(user_id=user_id, currency="points")
        return True, new_balance, False

    def reserve_sign_in(self, *, user_id: int, sign_date: str) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO sign_in_records (
                        group_id, user_id, sign_date
                    ) VALUES (?, ?, ?)""",
                    (self.group_id, user_id, sign_date),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def create_topic_and_charge(
        self,
        *,
        user_id: int,
        content: str,
        sign_date: str,
        cost_points: int = 5,
    ) -> Tuple[bool, Optional[int], int]:
        content_hash = sha1(content.encode("utf-8")).hexdigest()
        request_key = f"topic_create:{user_id}:{sign_date}:{content_hash}"

        with self.conn:
            cursor = self.conn.execute(
                """SELECT topic_id
                FROM topic_create_requests
                WHERE group_id = ? AND request_key = ?""",
                (self.group_id, request_key),
            )
            row = cursor.fetchone()
            if row and row[0]:
                balance = self.get_balance(user_id=user_id, currency="points")
                return False, int(row[0]), balance

            if not row:
                try:
                    self.conn.execute(
                        """INSERT INTO topic_create_requests (
                            group_id, request_key, user_id, topic_id
                        ) VALUES (?, ?, ?, NULL)""",
                        (self.group_id, request_key, user_id),
                    )
                except sqlite3.IntegrityError:
                    cursor = self.conn.execute(
                        """SELECT topic_id
                        FROM topic_create_requests
                        WHERE group_id = ? AND request_key = ?""",
                        (self.group_id, request_key),
                    )
                    existing = cursor.fetchone()
                    balance = self.get_balance(user_id=user_id, currency="points")
                    return False, int(existing[0]) if existing and existing[0] else None, balance

            balance = self.get_balance(user_id=user_id, currency="points")
            if balance < cost_points:
                self.conn.execute(
                    "DELETE FROM topic_create_requests WHERE group_id = ? AND request_key = ?",
                    (self.group_id, request_key),
                )
                return False, None, balance

            self.add_member(user_id)
            cursor = self.conn.execute(
                "INSERT INTO topics (proposer_id, content) VALUES (?, ?)",
                (user_id, content),
            )
            topic_id = int(cursor.lastrowid)
            self.update_member_stats(user_id, Activities.CREATED_TOPICS)
            self.record_engagement_event(
                domain_type="topic",
                subject_id=str(topic_id),
                actor_id=int(user_id),
                action="created",
                metadata={
                    "content": content,
                    "request_key": request_key,
                },
            )

            if int(cost_points or 0) > 0:
                idem_key = f"topic_create_cost:{self.group_id}:{request_key}"
                self.conn.execute(
                    """INSERT INTO points_ledger (
                        group_id,
                        user_id,
                        currency,
                        delta,
                        reason,
                        ref_type,
                        ref_id,
                        idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self.group_id,
                        user_id,
                        "points",
                        -int(cost_points),
                        "topic_create_cost",
                        "topic",
                        str(topic_id),
                        idem_key,
                    ),
                )
            self.conn.execute(
                """UPDATE topic_create_requests
                SET topic_id = ?
                WHERE group_id = ? AND request_key = ?""",
                (topic_id, self.group_id, request_key),
            )

        new_balance = self.get_balance(user_id=user_id, currency="points")
        return True, topic_id, new_balance

    def reserve_topic_vote(self, *, user_id: int, topic_id: int, choice: int) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO topic_votes (
                        group_id, topic_id, user_id, choice
                    ) VALUES (?, ?, ?, ?)""",
                    (self.group_id, int(topic_id), int(user_id), int(choice)),
                )
                self.record_engagement_event(
                    domain_type="topic",
                    subject_id=str(topic_id),
                    actor_id=int(user_id),
                    action="voted",
                    metadata={"choice": int(choice)},
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_member_stats(self, member_id: int) -> Dict[str, int]:
        with self.conn:
            cursor = self.conn.execute(
                """SELECT
                    created_topics,
                    created_activities,
                    voted_topics,
                    joined_activities,
                    published_works
                FROM members WHERE member_id = ?""",
                (member_id,),
            )
            row = cursor.fetchone()
            if row:
                columns = [column[0] for column in cursor.description]
                return dict(zip(columns, row))
            return {activity.value: 0 for activity in Activities}

    def update_member_stats(self, member_id: int, action: Activities) -> None:
        self.add_member(member_id)
        with self.conn:
            self.conn.execute(
                f"UPDATE members SET {action.value} = {action.value} + 1 WHERE member_id = ?",
                (member_id,),
            )

    def add_application(self, data: Dict[str, Any]) -> int:
        self.add_member(data["creator_id"])
        with self.conn:
            cursor = self.conn.execute(
                """INSERT INTO activity_applications (
                    creator_id, activity_name, requirement,
                    content, reward, duration
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    data["creator_id"],
                    data["activity_name"],
                    data["requirement"],
                    data["content"],
                    data["reward"],
                    data["duration"],
                ),
            )
            application_id = int(cursor.lastrowid)
            self.record_engagement_event(
                domain_type="activity",
                subject_id=f"application:{application_id}",
                actor_id=int(data["creator_id"]),
                action="applied",
                metadata={
                    "activity_name": data["activity_name"],
                    "duration": data["duration"],
                },
            )
            return application_id

    def get_application(self, application_id: int) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                "SELECT * FROM activity_applications WHERE application_id = ?",
                (application_id,),
            )
            row = cursor.fetchone()
            pprint(row)
            if row:
                columns = [column[0] for column in cursor.description]
                return dict(zip(columns, row))
            return None

    def remove_participant(self, user_id: int, activity_id: int) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                """UPDATE activity_memberships
                SET status = 'left', left_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND activity_id = ? AND status = 'active'""",
                (user_id, activity_id),
            )
            removed = cursor.rowcount > 0
            if removed:
                self.record_engagement_event(
                    domain_type="activity",
                    subject_id=str(activity_id),
                    actor_id=int(user_id),
                    action="left",
                )
            self.conn.commit()
            return removed

    def get_all_applications(self, status: int = 0) -> List[int]:
        with self.conn:
            cursor = self.conn.execute(
                "SELECT application_id FROM activity_applications WHERE status = ?",
                (status,),
            )
            return [row[0] for row in cursor.fetchall()]

    def get_all_activities(self) -> List[int]:
        with self.conn:
            cursor = self.conn.execute(
                "SELECT activity_id FROM activities "
                "WHERE status = 'active' "
                "AND strftime('%Y-%m-%dT%H:%M:%f', datetime('now', 'localtime')) BETWEEN start_time AND end_time"
            )
            return [row[0] for row in cursor.fetchall()]

    def update_application_field(self, application_id: int, field: str, value):
        if field not in _APPLICATION_MUTABLE_FIELDS:
            raise ValueError(f"illegal application field: {field}")
        application = self.get_application(application_id) if field == "status" else None
        with self.conn:
            self.conn.execute(
                f"UPDATE activity_applications SET {field} = ? WHERE application_id = ?",
                (value, application_id),
            )
            if field == "status" and application and application.get("creator_id") is not None:
                self.record_engagement_event(
                    domain_type="activity",
                    subject_id=f"application:{application_id}",
                    actor_id=int(application["creator_id"]),
                    action="application_status_changed",
                    metadata={
                        "from": application.get("status"),
                        "to": value,
                    },
                )
            self.conn.commit()

    def update_activity_field(self, activity_id: int, field: str, value):
        if field not in _ACTIVITY_MUTABLE_FIELDS:
            raise ValueError(f"illegal activity field: {field}")
        if field == "status" and value not in _ACTIVITY_STATUSES:
            raise ValueError(f"illegal activity status: {value}")
        activity = self.get_activity_by_activity_id(activity_id) if field == "status" else None
        with self.conn:
            self.conn.execute(
                f"UPDATE activities SET {field} = ? WHERE activity_id = ?",
                (value, activity_id),
            )
            if (
                field == "status"
                and activity
                and activity.get("creator_id") is not None
                and activity.get("status") != value
            ):
                self.record_engagement_event(
                    domain_type="activity",
                    subject_id=str(activity_id),
                    actor_id=int(activity["creator_id"]),
                    action="status_changed",
                    metadata={
                        "from": activity.get("status"),
                        "to": value,
                    },
                )
            self.conn.commit()

    def get_session(self, session_key: str) -> Optional[Dict[str, Any]]:
        with self.conn:
            cursor = self.conn.execute(
                "SELECT * FROM sessions WHERE session_key = ?",
                (session_key,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            columns = [column[0] for column in cursor.description]
            data = dict(zip(columns, row))
            try:
                data["data"] = json.loads(data.pop("data_json") or "{}")
            except json.JSONDecodeError:
                data["data"] = {}
            return data

    def create_session(
        self,
        session_key: str,
        flow: str,
        step: int,
        data: Dict[str, Any],
        owner_id: Optional[int],
        expires_at: datetime,
    ) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO sessions (
                        session_key, flow, step, data_json, owner_id, status, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_key,
                        flow,
                        step,
                        json.dumps(data or {}, ensure_ascii=False),
                        owner_id,
                        "active",
                        expires_at.isoformat(),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def update_session_step(
        self,
        session_key: str,
        step: int,
        data: Dict[str, Any],
        expected_version: int,
        expires_at: Optional[datetime] = None,
    ) -> bool:
        with self.conn:
            if expires_at:
                cursor = self.conn.execute(
                    """UPDATE sessions
                    SET step = ?, data_json = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP, expires_at = ?
                    WHERE session_key = ? AND version = ?""",
                    (
                        step,
                        json.dumps(data or {}, ensure_ascii=False),
                        expires_at.isoformat(),
                        session_key,
                        expected_version,
                    ),
                )
            else:
                cursor = self.conn.execute(
                    """UPDATE sessions
                    SET step = ?, data_json = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE session_key = ? AND version = ?""",
                    (
                        step,
                        json.dumps(data or {}, ensure_ascii=False),
                        session_key,
                        expected_version,
                    ),
                )
            return cursor.rowcount > 0

    def update_session_status(self, session_key: str, status: str) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                """UPDATE sessions
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_key = ?""",
                (status, session_key),
            )
            return cursor.rowcount > 0

    def cleanup_expired_sessions(self) -> int:
        with self.conn:
            cursor = self.conn.execute(
                f"DELETE FROM sessions WHERE datetime(expires_at) < {_SQLITE_NOW_EXPR}"
            )
            return cursor.rowcount

    def insert_audit_log(
        self,
        group_id: int,
        user_id: Optional[int],
        action: str,
        session_key: Optional[str],
        result: str,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO audit_logs (
                    group_id, user_id, action, session_key, result
                ) VALUES (?, ?, ?, ?, ?)""",
                (group_id, user_id, action, session_key, result),
            )

    def insert_audit_event(
        self,
        group_id: int,
        actor_id: Optional[int],
        action: str,
        subject_type: Optional[str],
        subject_id: Optional[str],
        session_key: Optional[str],
        result: str,
        context_json: str,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO audit_events (
                    group_id, actor_id, action, subject_type, subject_id,
                    session_key, result, context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    group_id,
                    actor_id,
                    action,
                    subject_type,
                    subject_id,
                    session_key,
                    result,
                    context_json,
                ),
            )

    def reserve_idempotency_key(
        self,
        idem_key: str,
        group_id: int,
        user_id: Optional[int],
        action: str,
        session_key: Optional[str],
    ) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO idempotency_keys (
                        idem_key, group_id, user_id, action, session_key
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (idem_key, group_id, user_id, action, session_key),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def reserve_vote_record(self, session_key: str, user_id: int, option_idx: int) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO vote_records (
                        session_key, user_id, option_idx
                    ) VALUES (?, ?, ?)""",
                    (session_key, user_id, option_idx),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def _migrate_schema(self) -> None:
        with self.conn:
            self._backfill_members_for_foreign_keys()
            self._migrate_governance_cases_statuses()
            self._migrate_governance_case_votes_shape()
            self._migrate_activities_status()
            self._migrate_activity_memberships()
            cursor = self.conn.execute("PRAGMA foreign_key_list(activity_applications)")
            rows = cursor.fetchall()
            has_creator_fk = any(row[2] == "members" and row[3] == "creator_id" for row in rows)
            if has_creator_fk:
                return
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_applications_new (
                    application_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_id INTEGER NOT NULL,
                    activity_name TEXT NOT NULL,
                    requirement TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reward TEXT NOT NULL,
                    duration INTEGER NOT NULL,
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status INTEGER DEFAULT 0,
                    FOREIGN KEY (creator_id) REFERENCES members(member_id)
                );
                INSERT INTO activity_applications_new (
                    application_id, creator_id, activity_name, requirement,
                    content, reward, duration, create_time, status
                )
                SELECT
                    application_id, creator_id, activity_name, requirement,
                    content, reward, duration, create_time, status
                FROM activity_applications;
                DROP TABLE activity_applications;
                ALTER TABLE activity_applications_new RENAME TO activity_applications;
            """
            )

    def _migrate_activities_status(self) -> None:
        cursor = self.conn.execute("PRAGMA table_info(activities)")
        cols = {row[1] for row in cursor.fetchall()}
        if "status" not in cols:
            self.conn.execute(
                "ALTER TABLE activities ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
            )
            self.conn.execute(
                "UPDATE activities SET status = 'ended' "
                "WHERE datetime(end_time) < datetime('now', 'localtime')"
            )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activities_status_time ON activities (status, start_time, end_time)"
        )

    def _migrate_governance_cases_statuses(self) -> None:
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'governance_cases'"
        ).fetchone()
        create_sql = str(row[0] or "") if row else ""
        if all(
            status in create_sql
            for status in ("nomination_publicity", "statement_and_questioning", "response_window", "runoff_voting")
        ):
            return

        self.conn.execute("PRAGMA foreign_keys = OFF")
        try:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS governance_cases_new (
                    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    proposer_id INTEGER NOT NULL,
                    target_user_id INTEGER,
                    status TEXT NOT NULL
                        CHECK (
                            status IN (
                                'supporting',
                                'nomination_publicity',
                                'statement_and_questioning',
                                'response_window',
                                'cooling',
                                'active',
                                'voting',
                                'runoff_voting',
                                'approved',
                                'rejected',
                                'cancelled'
                            )
                        ),
                    phase TEXT NOT NULL DEFAULT 'draft',
                    support_threshold INTEGER NOT NULL DEFAULT 0,
                    vote_duration_seconds INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    cooldown_until DATETIME,
                    vote_started_at DATETIME,
                    vote_ends_at DATETIME,
                    resolved_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (proposer_id) REFERENCES members(member_id),
                    FOREIGN KEY (target_user_id) REFERENCES members(member_id)
                );
                INSERT INTO governance_cases_new (
                    case_id, case_type, title, description, proposer_id, target_user_id,
                    status, phase, support_threshold, vote_duration_seconds, payload_json,
                    cooldown_until, vote_started_at, vote_ends_at, resolved_at, created_at, updated_at
                )
                SELECT
                    case_id, case_type, title, description, proposer_id, target_user_id,
                    status, phase, support_threshold, vote_duration_seconds, payload_json,
                    cooldown_until, vote_started_at, vote_ends_at, resolved_at, created_at, updated_at
                FROM governance_cases;
                DROP TABLE governance_cases;
                ALTER TABLE governance_cases_new RENAME TO governance_cases;
                CREATE INDEX IF NOT EXISTS idx_governance_cases_status_created
                    ON governance_cases (status, created_at);
            """
            )
        finally:
            self.conn.execute("PRAGMA foreign_keys = ON")

    def _migrate_governance_case_votes_shape(self) -> None:
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'governance_case_votes'"
        ).fetchone()
        create_sql = str(row[0] or "") if row else ""
        if "PRIMARY KEY (case_id, user_id, choice)" in create_sql:
            return

        self.conn.execute("PRAGMA foreign_keys = OFF")
        try:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS governance_case_votes_new (
                    case_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    choice INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (case_id, user_id, choice),
                    FOREIGN KEY (case_id) REFERENCES governance_cases(case_id),
                    FOREIGN KEY (user_id) REFERENCES members(member_id)
                );
                INSERT OR IGNORE INTO governance_case_votes_new (
                    case_id, user_id, choice, created_at
                )
                SELECT
                    case_id, user_id, choice, created_at
                FROM governance_case_votes;
                DROP TABLE governance_case_votes;
                ALTER TABLE governance_case_votes_new RENAME TO governance_case_votes;
                CREATE INDEX IF NOT EXISTS idx_governance_case_votes_case
                    ON governance_case_votes (case_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_governance_case_votes_case_user
                    ON governance_case_votes (case_id, user_id, created_at);
            """
            )
        finally:
            self.conn.execute("PRAGMA foreign_keys = ON")

    def _migrate_activity_memberships(self) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO activity_memberships (activity_id, user_id, status)
            SELECT activity_id, user_id, 'active'
            FROM participants
        """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO activity_memberships (activity_id, user_id, status)
            SELECT activity_id, creator_id, 'active'
            FROM activities
            WHERE creator_id IS NOT NULL
        """
        )

    def _backfill_members_for_foreign_keys(self) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO members (member_id)
            SELECT DISTINCT creator_id FROM activities
            WHERE creator_id IS NOT NULL
        """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO members (member_id)
            SELECT DISTINCT proposer_id FROM topics
            WHERE proposer_id IS NOT NULL
        """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO members (member_id)
            SELECT DISTINCT user_id FROM participants
            WHERE user_id IS NOT NULL
        """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO members (member_id)
            SELECT DISTINCT creator_id FROM activity_applications
            WHERE creator_id IS NOT NULL
        """
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO members (member_id)
            SELECT DISTINCT user_id FROM activity_memberships
            WHERE user_id IS NOT NULL
        """
        )
def _expires_at_from_ttl(ttl_seconds: int) -> datetime:
    return datetime.now() + timedelta(seconds=ttl_seconds)


_ACTIVITY_STATUSES = {"draft", "active", "ended", "cancelled"}
_ACTIVITY_MUTABLE_FIELDS = {
    "start_time",
    "end_time",
    "activity_name",
    "requirement",
    "content",
    "reward",
    "creator_id",
    "status",
}
_APPLICATION_MUTABLE_FIELDS = {
    "creator_id",
    "activity_name",
    "requirement",
    "content",
    "reward",
    "duration",
    "create_time",
    "status",
}


def get_session(db: GroupDatabase, session_key: str) -> Optional[Dict[str, Any]]:
    return db.get_session(session_key)


def create_session(
    db: GroupDatabase,
    session_key: str,
    flow: str,
    owner_id: Optional[int],
    ttl_seconds: int,
    initial_data: Optional[Dict[str, Any]] = None,
) -> bool:
    return db.create_session(
        session_key=session_key,
        flow=flow,
        step=0,
        data=initial_data or {},
        owner_id=owner_id,
        expires_at=_expires_at_from_ttl(ttl_seconds),
    )


def update_session_step(
    db: GroupDatabase,
    session_key: str,
    step: int,
    patch_data: Optional[Dict[str, Any]],
    expected_version: int,
    ttl_seconds: Optional[int] = None,
) -> bool:
    session = db.get_session(session_key)
    if not session:
        return False
    merged = dict(session.get("data") or {})
    if patch_data:
        merged.update(patch_data)
    expires_at = _expires_at_from_ttl(ttl_seconds) if ttl_seconds else None
    return db.update_session_step(
        session_key=session_key,
        step=step,
        data=merged,
        expected_version=expected_version,
        expires_at=expires_at,
    )


def finish_session(db: GroupDatabase, session_key: str) -> bool:
    return db.update_session_status(session_key, "finished")


def cancel_session(db: GroupDatabase, session_key: str) -> bool:
    return db.update_session_status(session_key, "cancelled")


def cleanup_expired_sessions(db: GroupDatabase) -> int:
    return db.cleanup_expired_sessions()


def record_audit_log(
    db: GroupDatabase,
    group_id: int,
    user_id: Optional[int],
    action: str,
    session_key: Optional[str],
    result: str,
) -> None:
    db.insert_audit_log(group_id, user_id, action, session_key, result)


def record_audit_event(
    db: GroupDatabase,
    group_id: int,
    actor_id: Optional[int],
    action: str,
    subject_type: Optional[str],
    subject_id: Optional[str],
    session_key: Optional[str],
    result: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    context_json = json.dumps(context or {}, ensure_ascii=False)
    db.insert_audit_event(
        group_id,
        actor_id,
        action,
        subject_type,
        subject_id,
        session_key,
        result,
        context_json,
    )


def reserve_idempotency_key(
    db: GroupDatabase,
    idem_key: str,
    group_id: int,
    user_id: Optional[int],
    action: str,
    session_key: Optional[str],
) -> bool:
    return db.reserve_idempotency_key(idem_key, group_id, user_id, action, session_key)


def reserve_vote_record(
    db: GroupDatabase,
    session_key: str,
    user_id: int,
    option_idx: int,
) -> bool:
    return db.reserve_vote_record(session_key, user_id, option_idx)


def add_topic(db: GroupDatabase, proposer_id: int, content: str) -> int:
    return db.add_topic(proposer_id, content)


def update_member_stats(db: GroupDatabase, member_id: int, action: Activities) -> None:
    db.update_member_stats(member_id, action)


def add_activity_application(db: GroupDatabase, data: Dict[str, Any]) -> int:
    return db.add_application(data)


def update_activity_application_field(
    db: GroupDatabase,
    application_id: int,
    field: str,
    value: Any,
) -> None:
    if field not in _APPLICATION_MUTABLE_FIELDS:
        raise ValueError(f"illegal application field: {field}")
    db.update_application_field(application_id, field, value)


def update_activity_field(
    db: GroupDatabase,
    activity_id: int,
    field: str,
    value: Any,
) -> None:
    if field not in _ACTIVITY_MUTABLE_FIELDS:
        raise ValueError(f"illegal activity field: {field}")
    if field == "status" and value not in _ACTIVITY_STATUSES:
        raise ValueError(f"illegal activity status: {value}")
    db.update_activity_field(activity_id, field, value)


def add_activity(
    db: GroupDatabase,
    *,
    creator_id: int,
    activity_name: str,
    requirement: str,
    content: str,
    reward: str,
    start: datetime,
    end: datetime,
    status: str = "active",
    source_application_id: Optional[int] = None,
) -> int:
    if status not in _ACTIVITY_STATUSES:
        raise ValueError(f"illegal activity status: {status}")
    return db.add_activity(
        creator_id=creator_id,
        activity_name=activity_name,
        requirement=requirement,
        content=content,
        reward=reward,
        start=start,
        end=end,
        status=status,
        source_application_id=source_application_id,
    )


def add_activity_participant(
    db: GroupDatabase,
    *,
    user_id: int,
    activity_id: int,
) -> tuple[bool, str]:
    return db.add_participant(user_id, activity_id)


def remove_activity_participant(
    db: GroupDatabase,
    *,
    user_id: int,
    activity_id: int,
) -> bool:
    return db.remove_participant(user_id, activity_id)


def provision_bot_user(
    db: InternalDatabase,
    qq_uin: str,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    existing = db.get_bot_user_by_qq(qq_uin)
    issued_secret = secrets.token_urlsafe(32)
    if existing:
        if display_name and display_name != existing.get("display_name"):
            db.update_bot_user_display_name(existing["user_id"], display_name)
        db.update_bot_user_secret(existing["user_id"], issued_secret)
        user = db.get_bot_user_by_qq(qq_uin) or {}
        user["secret"] = issued_secret
        return user
    user_id = uuid.uuid4().hex
    db.create_bot_user(
        user_id=user_id,
        qq_uin=qq_uin,
        display_name=display_name,
        status="pending",
        secret=issued_secret,
    )
    db.ensure_bot_rank(user_id)
    user = db.get_bot_user_by_qq(qq_uin) or {}
    user["secret"] = issued_secret
    return user


def confirm_bot_user(db: InternalDatabase, qq_uin: str) -> Optional[Dict[str, Any]]:
    user = db.get_bot_user_by_qq(qq_uin)
    if not user:
        return None
    if user.get("status") != "active":
        db.update_bot_user_status(user["user_id"], "active")
    return db.get_bot_user_by_qq(qq_uin)


def reserve_bot_nonce(
    db: InternalDatabase,
    bot_id: str,
    nonce: str,
    ttl_seconds: int,
) -> bool:
    db.cleanup_expired_nonces()
    expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
    return db.reserve_bot_nonce(bot_id=bot_id, nonce=nonce, expires_at=expires_at)


def create_bot_session(
    db: InternalDatabase,
    qq_uin: str,
    secret: str,
    ttl_seconds: int,
) -> Optional[Dict[str, Any]]:
    user = db.get_bot_user_by_secret(qq_uin, secret)
    if not user or user.get("status") != "active":
        return None
    db.cleanup_expired_bot_sessions()
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
    db.create_bot_session(session_id=session_id, user_id=user["user_id"], expires_at=expires_at)
    db.update_bot_user_last_login(user["user_id"])
    return {
        "session_id": session_id,
        "expires_at": expires_at,
        "user_id": user["user_id"],
    }


