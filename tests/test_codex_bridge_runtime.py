import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.support.api as support_module


def test_extract_codex_session_id_from_json_events():
    stdout = (
        b'{"type":"thread.started","thread_id":"thread-123"}\n'
        b'{"type":"turn.started"}\n'
        b'{"type":"item.completed","item":{"text":"ok"}}\n'
    )

    assert support_module.CodexBridge._extract_codex_session_id(stdout) == "thread-123"


def test_build_exec_command_uses_resume_session(tmp_path):
    bridge = object.__new__(support_module.CodexBridge)
    output_path = tmp_path / "result.txt"
    ctx = support_module.CodexJobContext(
        job_id="job1",
        bot_self_id="bot",
        user_id=1,
        group_id=None,
        chat_type="private",
        prompt="继续处理",
        source_message_id="msg1",
        command=["codex", "exec", "--skip-git-repo-check"],
        workdir=str(tmp_path),
        codex_session_id="thread-123",
        resume_mode="resume",
    )

    command = bridge._build_exec_command(ctx, output_path)

    assert command == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "-C",
        str(tmp_path),
        "--json",
        "-o",
        str(output_path),
        "resume",
        "thread-123",
        "继续处理",
    ]


def test_resume_failure_triggers_fallback_to_new(tmp_path):
    ctx = support_module.CodexJobContext(
        job_id="job2",
        bot_self_id="bot",
        user_id=1,
        group_id=None,
        chat_type="private",
        prompt="重新开始",
        source_message_id="msg2",
        command=["codex", "exec"],
        workdir=str(tmp_path),
        codex_session_id="thread-dead",
        resume_mode="resume",
    )

    stderr = b"failed to resume session: session not found"

    assert support_module.CodexBridge._should_fallback_to_new(ctx, 1, b"", stderr) is True
    assert support_module.CodexBridge._should_fallback_to_new(ctx, 0, b"", stderr) is False


def test_fallback_new_still_uses_stdin(tmp_path):
    ctx = support_module.CodexJobContext(
        job_id="job4",
        bot_self_id="bot",
        user_id=1,
        group_id=None,
        chat_type="private",
        prompt="重新开始",
        source_message_id="msg4",
        command=["codex", "exec"],
        workdir=str(tmp_path),
        codex_session_id=None,
        resume_mode="fallback-new",
    )

    assert support_module.CodexBridge._uses_stdin(ctx) is True


def test_non_session_failure_does_not_trigger_fallback(tmp_path):
    ctx = support_module.CodexJobContext(
        job_id="job3",
        bot_self_id="bot",
        user_id=1,
        group_id=None,
        chat_type="private",
        prompt="重新开始",
        source_message_id="msg3",
        command=["codex", "exec"],
        workdir=str(tmp_path),
        codex_session_id="thread-dead",
        resume_mode="resume",
    )

    stderr = b"Not inside a trusted directory and --skip-git-repo-check was not specified."

    assert support_module.CodexBridge._should_fallback_to_new(ctx, 1, b"", stderr) is False
