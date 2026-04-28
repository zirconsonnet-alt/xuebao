from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.services.sign_in as sign_in_module
from src.services.sign_in import SignInUseCase, sample_sign_in_points
from src.support.db import GroupDatabase


def test_sign_in_is_idempotent_per_day(tmp_path: Path) -> None:
    db = GroupDatabase(group_id=777, data_root=tmp_path)
    try:
        sampled_points = iter([1, 2])
        uc = SignInUseCase(points_sampler=lambda: next(sampled_points))
        now = datetime(2026, 2, 6, 12, 0, 0)

        r1 = uc.execute(db=db, group_id=777, user_id=42, now=now)
        assert r1.sign_date == "2026-02-06"
        assert r1.signed_in is True
        assert r1.awarded_points == 1
        assert r1.points_balance == 1

        r2 = uc.execute(db=db, group_id=777, user_id=42, now=now)
        assert r2.sign_date == "2026-02-06"
        assert r2.signed_in is False
        assert r2.awarded_points == 0
        assert r2.points_balance == 1

        r3 = uc.execute(db=db, group_id=777, user_id=42, now=datetime(2026, 2, 7, 1, 0, 0))
        assert r3.sign_date == "2026-02-07"
        assert r3.signed_in is True
        assert r3.awarded_points == 2
        assert r3.points_balance == 3
    finally:
        db.conn.close()


def test_sample_sign_in_points_rounds_and_clamps(monkeypatch) -> None:
    monkeypatch.setattr(sign_in_module.random, "gauss", lambda mean, stddev: 50.4)
    assert sample_sign_in_points() == 50

    monkeypatch.setattr(sign_in_module.random, "gauss", lambda mean, stddev: 10.4)
    assert sample_sign_in_points() == 10

    monkeypatch.setattr(sign_in_module.random, "gauss", lambda mean, stddev: 0.49)
    assert sample_sign_in_points() == 1
