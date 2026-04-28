import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..spec import get_law_template_dir


_OPEN_CASE_STATUSES = (
    "supporting",
    "nomination_publicity",
    "statement_and_questioning",
    "response_window",
    "cooling",
    "active",
    "voting",
    "runoff_voting",
)


class GovernanceStorage:
    def __init__(self, db):
        self.db = db

    def import_law_templates(self, laws_path: Path) -> int:
        source_dir = get_law_template_dir()
        if not source_dir.exists():
            return 0
        laws_path.mkdir(parents=True, exist_ok=True)
        imported = 0
        for file_path in sorted(source_dir.glob("*.txt")):
            content = file_path.read_text(encoding="utf-8")
            (laws_path / file_path.name).write_text(content, encoding="utf-8")
            imported += 1
        return imported

    def upsert_member_profile(self, member: Dict[str, Any]) -> None:
        user_id = int(member.get("user_id") or 0)
        if user_id <= 0:
            return
        self.db.add_member(user_id)
        with self.db.conn:
            self.db.conn.execute(
                """
                INSERT INTO member_profiles (
                    user_id, nickname, card, role_code, title, join_time, last_sent_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    nickname = excluded.nickname,
                    card = excluded.card,
                    role_code = excluded.role_code,
                    title = excluded.title,
                    join_time = excluded.join_time,
                    last_sent_time = excluded.last_sent_time,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (
                    user_id,
                    str(member.get("nickname") or ""),
                    str(member.get("card") or ""),
                    str(member.get("role") or "member").strip().lower() or "member",
                    str(member.get("title") or ""),
                    member.get("join_time"),
                    member.get("last_sent_time"),
                ),
            )

    def get_member_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.fetchone(
            """
            SELECT user_id, nickname, card, role_code, title, join_time, last_sent_time
            FROM member_profiles
            WHERE user_id = ?
        """,
            (user_id,),
        )

    def member_count(self) -> int:
        row = self.fetchone("SELECT COUNT(*) AS total FROM member_profiles")
        return int((row or {}).get("total") or 0)

    def get_platform_human_admin_ids(self, self_id: int) -> List[int]:
        rows = self.fetchall(
            """
            SELECT user_id
            FROM member_profiles
            WHERE role_code = 'admin' AND user_id != ?
            ORDER BY user_id
        """,
            (self_id,),
        )
        return [int(row["user_id"]) for row in rows]

    def set_role_status(
        self,
        *,
        user_id: int,
        role_code: str,
        status: str,
        source: str,
        operator_id: int,
        notes: str,
    ) -> None:
        self.db.add_member(user_id)
        self.db.add_member(operator_id)
        with self.db.conn:
            self.db.conn.execute(
                """
                INSERT INTO governance_roles (
                    user_id, role_code, status, source, operator_id, notes, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(user_id, role_code) DO UPDATE SET
                    status = excluded.status,
                    source = excluded.source,
                    operator_id = excluded.operator_id,
                    notes = excluded.notes,
                    revoked_at = CASE WHEN excluded.status = 'active' THEN NULL ELSE CURRENT_TIMESTAMP END,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (user_id, role_code, status, source, operator_id, notes),
            )

    def revoke_role(self, user_id: int, role_code: str, *, operator_id: int, notes: str) -> None:
        self.db.add_member(user_id)
        self.db.add_member(operator_id)
        with self.db.conn:
            self.db.conn.execute(
                """
                UPDATE governance_roles
                SET status = 'revoked',
                    operator_id = ?,
                    notes = ?,
                    revoked_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND role_code = ? AND status = 'active'
            """,
                (operator_id, notes, user_id, role_code),
            )

    def revoke_all_roles(self, role_code: str, *, operator_id: int, notes: str) -> None:
        self.db.add_member(operator_id)
        with self.db.conn:
            self.db.conn.execute(
                """
                UPDATE governance_roles
                SET status = 'revoked',
                    operator_id = ?,
                    notes = ?,
                    revoked_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE role_code = ? AND status = 'active'
            """,
                (operator_id, notes, role_code),
            )

    def has_role(self, user_id: int, role_code: str) -> bool:
        row = self.fetchone(
            """
            SELECT user_id
            FROM governance_roles
            WHERE user_id = ? AND role_code = ? AND status = 'active'
            LIMIT 1
        """,
            (user_id, role_code),
        )
        return row is not None

    def get_active_role_user(self, role_code: str) -> Optional[int]:
        row = self.fetchone(
            """
            SELECT user_id
            FROM governance_roles
            WHERE role_code = ? AND status = 'active'
            ORDER BY updated_at DESC, user_id DESC
            LIMIT 1
        """,
            (role_code,),
        )
        return int(row["user_id"]) if row else None

    def get_active_role_users(self, role_code: str) -> List[int]:
        rows = self.fetchall(
            """
            SELECT user_id
            FROM governance_roles
            WHERE role_code = ? AND status = 'active'
            ORDER BY user_id
        """,
            (role_code,),
        )
        return [int(row["user_id"]) for row in rows]

    def create_case(
        self,
        *,
        case_type: str,
        title: str,
        description: str,
        proposer_id: int,
        target_user_id: Optional[int],
        status: str,
        phase: str,
        support_threshold: int,
        vote_duration_seconds: int,
        payload: Dict[str, Any],
    ) -> int:
        self.db.add_member(proposer_id)
        if target_user_id:
            self.db.add_member(target_user_id)
        with self.db.conn:
            cursor = self.db.conn.execute(
                """
                INSERT INTO governance_cases (
                    case_type, title, description, proposer_id, target_user_id,
                    status, phase, support_threshold, vote_duration_seconds, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    case_type,
                    title,
                    description,
                    proposer_id,
                    target_user_id,
                    status,
                    phase,
                    int(support_threshold),
                    int(vote_duration_seconds),
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
        return int(cursor.lastrowid)

    def get_case(self, case_id: int) -> Optional[Dict[str, Any]]:
        return self.fetchone(
            """
            SELECT case_id, case_type, title, description, proposer_id, target_user_id,
                status, phase, support_threshold, vote_duration_seconds, payload_json,
                cooldown_until, vote_started_at, vote_ends_at, resolved_at, created_at, updated_at
            FROM governance_cases
            WHERE case_id = ?
        """,
            (case_id,),
        )

    def list_recent_cases(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.fetchall(
            """
            SELECT case_id, case_type, status, phase, target_user_id, proposer_id,
                support_threshold, cooldown_until, payload_json, resolved_at, created_at
            FROM governance_cases
            ORDER BY case_id DESC
            LIMIT ?
        """,
            (limit,),
        )

    def list_active_cases(self, limit: int = 8) -> List[Dict[str, Any]]:
        placeholders = ",".join("?" for _ in _OPEN_CASE_STATUSES)
        return self.fetchall(
            f"""
            SELECT case_id, case_type, status, phase, target_user_id, proposer_id,
                support_threshold, cooldown_until, payload_json, resolved_at
            FROM governance_cases
            WHERE status IN ({placeholders})
            ORDER BY case_id DESC
            LIMIT ?
        """,
            (*_OPEN_CASE_STATUSES, limit),
        )

    def find_open_case(self, case_type: str, target_user_id: Optional[int]) -> Optional[Dict[str, Any]]:
        placeholders = ",".join("?" for _ in _OPEN_CASE_STATUSES)
        if target_user_id is None:
            return self.fetchone(
                f"""
                SELECT case_id, status
                FROM governance_cases
                WHERE case_type = ?
                    AND target_user_id IS NULL
                    AND status IN ({placeholders})
                ORDER BY case_id DESC
                LIMIT 1
            """,
                (case_type, *_OPEN_CASE_STATUSES),
            )
        return self.fetchone(
            f"""
            SELECT case_id, status
            FROM governance_cases
            WHERE case_type = ?
                AND target_user_id = ?
                AND status IN ({placeholders})
            ORDER BY case_id DESC
            LIMIT 1
        """,
            (case_type, target_user_id, *_OPEN_CASE_STATUSES),
        )

    def find_open_case_by_type(self, case_type: str) -> Optional[Dict[str, Any]]:
        placeholders = ",".join("?" for _ in _OPEN_CASE_STATUSES)
        return self.fetchone(
            f"""
            SELECT case_id, status, target_user_id
            FROM governance_cases
            WHERE case_type = ?
                AND status IN ({placeholders})
            ORDER BY case_id DESC
            LIMIT 1
        """,
            (case_type, *_OPEN_CASE_STATUSES),
        )

    def update_case_fields(self, case_id: int, patch: Dict[str, Any]) -> None:
        if not patch:
            return
        allowed_fields = {
            "status",
            "phase",
            "support_threshold",
            "payload_json",
            "cooldown_until",
            "vote_started_at",
            "vote_ends_at",
            "resolved_at",
        }
        assignments: List[str] = []
        values: List[Any] = []
        for field_name, value in patch.items():
            if field_name not in allowed_fields:
                continue
            assignments.append(f"{field_name} = ?")
            if field_name == "payload_json" and not isinstance(value, str):
                values.append(json.dumps(value or {}, ensure_ascii=False))
            else:
                values.append(value)
        if not assignments:
            return
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        values.append(case_id)
        with self.db.conn:
            self.db.conn.execute(
                f"UPDATE governance_cases SET {', '.join(assignments)} WHERE case_id = ?",
                tuple(values),
            )

    def resolve_case_status(self, *, case_id: int, status: str, phase: str, resolved_at: str) -> None:
        self.update_case_fields(
            case_id,
            {"status": status, "phase": phase, "resolved_at": resolved_at},
        )

    def add_case_support(self, case_id: int, user_id: int) -> bool:
        self.db.add_member(user_id)
        try:
            with self.db.conn:
                self.db.conn.execute(
                    """
                    INSERT INTO governance_case_supporters (case_id, user_id)
                    VALUES (?, ?)
                """,
                    (case_id, user_id),
                )
            return True
        except Exception:
            return False

    def count_case_supporters(self, case_id: int) -> int:
        row = self.fetchone(
            "SELECT COUNT(*) AS total FROM governance_case_supporters WHERE case_id = ?",
            (case_id,),
        )
        return int((row or {}).get("total") or 0)

    def has_case_vote(self, case_id: int, user_id: int) -> bool:
        row = self.fetchone(
            """
            SELECT 1
            FROM governance_case_votes
            WHERE case_id = ? AND user_id = ?
            LIMIT 1
        """,
            (case_id, user_id),
        )
        return row is not None

    def reserve_case_votes(self, case_id: int, user_id: int, choices: List[int]) -> bool:
        self.db.add_member(user_id)
        normalized_choices = sorted({int(choice) for choice in choices if int(choice) > 0})
        if not normalized_choices:
            return False
        if self.has_case_vote(case_id, user_id):
            return False
        try:
            with self.db.conn:
                self.db.conn.executemany(
                    """
                    INSERT INTO governance_case_votes (case_id, user_id, choice)
                    VALUES (?, ?, ?)
                """,
                    [(case_id, user_id, choice) for choice in normalized_choices],
                )
            return True
        except Exception:
            return False

    def count_case_votes(self, case_id: int) -> Dict[int, int]:
        rows = self.fetchall(
            """
            SELECT choice, COUNT(*) AS total
            FROM governance_case_votes
            WHERE case_id = ?
            GROUP BY choice
        """,
            (case_id,),
        )
        counts: Dict[int, int] = {}
        for row in rows:
            counts[int(row["choice"])] = int(row["total"])
        return counts

    def count_case_voters(self, case_id: int) -> int:
        row = self.fetchone(
            """
            SELECT COUNT(DISTINCT user_id) AS total
            FROM governance_case_votes
            WHERE case_id = ?
        """,
            (case_id,),
        )
        return int((row or {}).get("total") or 0)

    def delete_case_votes(self, case_id: int) -> None:
        with self.db.conn:
            self.db.conn.execute(
                "DELETE FROM governance_case_votes WHERE case_id = ?",
                (case_id,),
            )

    def upsert_lock(
        self,
        *,
        lock_key: str,
        lock_type: str,
        target_user_id: Optional[int],
        source_case_id: Optional[int],
        reason: str,
        payload: Dict[str, Any],
    ) -> None:
        if target_user_id:
            self.db.add_member(target_user_id)
        with self.db.conn:
            self.db.conn.execute(
                """
                INSERT INTO governance_freeze_locks (
                    lock_key, lock_type, target_user_id, source_case_id, reason, payload_json, active, released_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, NULL)
                ON CONFLICT(lock_key) DO UPDATE SET
                    lock_type = excluded.lock_type,
                    target_user_id = excluded.target_user_id,
                    source_case_id = excluded.source_case_id,
                    reason = excluded.reason,
                    payload_json = excluded.payload_json,
                    active = 1,
                    released_at = NULL
            """,
                (
                    lock_key,
                    lock_type,
                    target_user_id,
                    source_case_id,
                    reason,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )

    def release_case_locks(self, case_id: int) -> None:
        with self.db.conn:
            self.db.conn.execute(
                """
                UPDATE governance_freeze_locks
                SET active = 0,
                    released_at = CURRENT_TIMESTAMP
                WHERE source_case_id = ? AND active = 1
            """,
                (case_id,),
            )

    def release_lock(self, lock_key: str) -> None:
        with self.db.conn:
            self.db.conn.execute(
                """
                UPDATE governance_freeze_locks
                SET active = 0,
                    released_at = CURRENT_TIMESTAMP
                WHERE lock_key = ? AND active = 1
            """,
                (lock_key,),
            )

    def has_active_lock(self, *, lock_type: str, target_user_id: Optional[int] = None) -> bool:
        if target_user_id is None:
            row = self.fetchone(
                """
                SELECT lock_key
                FROM governance_freeze_locks
                WHERE lock_type = ? AND active = 1
                LIMIT 1
            """,
                (lock_type,),
            )
        else:
            row = self.fetchone(
                """
                SELECT lock_key
                FROM governance_freeze_locks
                WHERE lock_type = ? AND target_user_id = ? AND active = 1
                LIMIT 1
            """,
                (lock_type, target_user_id),
            )
        return row is not None

    def get_active_lock(self, *, lock_type: str, target_user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if target_user_id is None:
            return self.fetchone(
                """
                SELECT lock_key, lock_type, target_user_id, source_case_id, reason, payload_json
                FROM governance_freeze_locks
                WHERE lock_type = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (lock_type,),
            )
        return self.fetchone(
            """
            SELECT lock_key, lock_type, target_user_id, source_case_id, reason, payload_json
            FROM governance_freeze_locks
            WHERE lock_type = ? AND target_user_id = ? AND active = 1
            ORDER BY created_at DESC
            LIMIT 1
        """,
            (lock_type, target_user_id),
        )

    def list_active_locks(self) -> List[Dict[str, Any]]:
        return self.fetchall(
            """
            SELECT lock_key, lock_type, target_user_id, source_case_id, reason, payload_json
            FROM governance_freeze_locks
            WHERE active = 1
            ORDER BY created_at DESC
        """
        )

    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
        cursor = self.db.conn.execute(query, params)
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [column[0] for column in cursor.description or []]
        return self._normalize_row(dict(zip(columns, row)))

    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        cursor = self.db.conn.execute(query, params)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description or []]
        return [self._normalize_row(dict(zip(columns, row))) for row in rows]

    @staticmethod
    def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(row)
        if "payload_json" in normalized:
            try:
                normalized["payload"] = json.loads(normalized.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                normalized["payload"] = {}
        return normalized


__all__ = [
    "GovernanceStorage",
]
