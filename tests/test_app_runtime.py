from pathlib import Path
import asyncio
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import bot  # noqa: F401
import src.app as app_module


def test_iter_daily_release_group_ids_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("DAILY_RELEASE_GROUP_IDS", "766072328, 123456, invalid, 766072328")

    assert app_module._iter_daily_release_group_ids() == [766072328, 123456]


def test_should_run_auto_organize_fallback_only_when_runtime_task_missing() -> None:
    enabled_service = SimpleNamespace(enabled=True, auto_organize_enabled=True)
    disabled_service = SimpleNamespace(enabled=True, auto_organize_enabled=False)

    assert app_module._should_run_auto_organize_fallback(enabled_service, None) is True
    assert (
        app_module._should_run_auto_organize_fallback(
            enabled_service,
            {"enabled": True},
        )
        is False
    )
    assert app_module._should_run_auto_organize_fallback(disabled_service, None) is False


def test_send_law_forward_chunks_retries_failed_batch(monkeypatch) -> None:
    sleeps = []
    calls = []
    failed_once = False

    async def fake_sleep(delay):
        sleeps.append(delay)

    async def send_chunk(chunk):
        nonlocal failed_once
        calls.append(chunk)
        if chunk == ["b"] and not failed_once:
            failed_once = True
            raise RuntimeError("temporary failure")

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)

    asyncio.run(app_module._send_law_forward_chunks([["a"], ["b"]], send_chunk))

    assert calls == [["a"], ["b"], ["b"]]
    assert sleeps == [
        app_module.LAW_ORIGINAL_FORWARD_BATCH_DELAY_SECONDS,
        app_module.LAW_ORIGINAL_FORWARD_BATCH_DELAY_SECONDS,
    ]


def test_send_law_forward_chunks_reports_failed_batch(monkeypatch) -> None:
    async def fake_sleep(delay):
        pass

    async def send_chunk(chunk):
        raise RuntimeError("permanent failure")

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)

    try:
        asyncio.run(app_module._send_law_forward_chunks([["a"], ["b"]], send_chunk))
    except app_module.LawOriginalForwardSendError as exc:
        assert exc.index == 1
        assert exc.total == 2
        assert isinstance(exc.original, RuntimeError)
    else:
        raise AssertionError("expected LawOriginalForwardSendError")
