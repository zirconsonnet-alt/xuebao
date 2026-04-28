from datetime import datetime, timedelta
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.support.api as api_module
from src.support.db import GroupDatabase, InternalDatabase


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_module.internal_api_router)
    return app


def test_cleanup_expired_nonce_and_group_session(tmp_path: Path) -> None:
    internal = InternalDatabase(db_path=tmp_path / "internal_api.db")
    try:
        assert internal.reserve_bot_nonce(
            bot_id="bot-1",
            nonce="nonce-1",
            expires_at=datetime.now() - timedelta(seconds=5),
        )
        assert internal.cleanup_expired_nonces() == 1
    finally:
        internal.close()

    group_db = GroupDatabase(group_id=123, data_root=tmp_path)
    try:
        assert group_db.create_session(
            session_key="session-1",
            flow="demo",
            step=0,
            data={},
            owner_id=1,
            expires_at=datetime.now() - timedelta(seconds=5),
        )
        assert group_db.cleanup_expired_sessions() == 1
    finally:
        group_db.conn.close()


def test_auth_cookie_roundtrip_and_logout(tmp_path: Path, monkeypatch) -> None:
    db = InternalDatabase(db_path=tmp_path / "internal_api.db")
    old_db = api_module._internal_db
    monkeypatch.setattr(api_module, "_internal_db", db)

    try:
        db.create_bot_user(
            user_id="user-1",
            qq_uin="10001",
            display_name="Tester",
            status="active",
            secret="secret-1",
        )
        db.ensure_bot_rank("user-1")

        client = TestClient(_build_app(), base_url="https://testserver")

        login = client.post("/auth/login", json={"qq_uin": "10001", "secret": "secret-1"})
        assert login.status_code == 200
        assert api_module.bot_api_config.cookie_name in client.cookies

        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["user_id"] == "user-1"
        assert me.json()["qq_uin"] == "10001"

        logout = client.post("/auth/logout")
        assert logout.status_code == 200

        me_again = client.get("/auth/me")
        assert me_again.status_code == 401
    finally:
        monkeypatch.setattr(api_module, "_internal_db", old_db)
        db.close()


def test_create_bot_user_hashes_secret_before_storage(tmp_path: Path) -> None:
    db = InternalDatabase(db_path=tmp_path / "internal_api.db")
    try:
        db.create_bot_user(
            user_id="user-1",
            qq_uin="10001",
            display_name="Tester",
            status="active",
            secret="secret-1",
        )

        stored = db.get_bot_user_by_qq("10001")

        assert stored is not None
        assert stored["secret"] == ""
        assert stored["secret_hash"]
        assert db.get_bot_user_by_secret("10001", "secret-1") is not None
        assert db.get_bot_user_by_secret("10001", "wrong-secret") is None
    finally:
        db.close()


def test_auth_login_invalid_payload_returns_400(tmp_path: Path, monkeypatch) -> None:
    db = InternalDatabase(db_path=tmp_path / "internal_api.db")
    old_db = api_module._internal_db
    monkeypatch.setattr(api_module, "_internal_db", db)

    try:
        client = TestClient(_build_app())
        response = client.post("/auth/login", json={"qq_uin": "10001"})
        assert response.status_code == 400
    finally:
        monkeypatch.setattr(api_module, "_internal_db", old_db)
        db.close()
