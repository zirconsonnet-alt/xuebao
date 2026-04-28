import json
from contextlib import contextmanager
from pathlib import Path
import sys
from typing import Iterator

import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message

from nonebug import App


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


pytestmark = pytest.mark.asyncio

_TRANSCRIPT_DIR = REPO_ROOT / ".codex_tmp" / "governance_test_transcripts"
_TRANSCRIPT_INITIALIZED: set[str] = set()
_TRANSCRIPT_SEQUENCES: dict[str, int] = {}

_VOTE_SERVICE_COMMANDS = [
    ("service_entry", "投票服务", False),
    ("enable_service", "开启投票服务", False),
    ("disable_service", "关闭投票服务", False),
    ("start_topic_vote", "发起议题", False),
    ("start_kick_vote", "发起放逐", False),
    ("start_ban_vote", "发起禁言", False),
    ("start_general_vote", "发起投票", False),
    ("initialize_governance", "治理初始化", False),
    ("sync_governance_members", "同步治理成员", False),
    ("show_governance_status", "查看治理状态", False),
    ("show_command_usage", "指令用法", True),
    ("set_honor_owner", "设置荣誉群主", True),
    ("add_elder", "添加元老", True),
    ("remove_elder", "移除元老", True),
    ("create_honor_owner_election", "发起荣誉群主选举", True),
    ("create_elder_election", "发起元老选举", True),
    ("create_honor_owner_impeachment", "发起弹劾荣誉群主", True),
    ("create_elder_impeachment", "发起弹劾元老", True),
    ("create_elder_reboot", "发起重组元老会", True),
    ("create_emergency_protection", "发起紧急防护", True),
    ("create_formal_discipline", "发起正式处分", True),
    ("daily_management", "日常管理", True),
    ("create_formal_discipline_review", "申请处分复核", True),
    ("create_governance_proposal", "发起提案", True),
    ("review_governance_proposal", "审查提案", True),
    ("correct_governance_proposal", "补正提案", True),
    ("request_governance_proposal_review", "申请提案复核", True),
    ("designate_temporary_proxy", "指定临时代理", True),
    ("create_vacancy_dispute_vote", "发起职权争议表决", True),
    ("support_governance_case", "联署治理案件", True),
    ("advance_governance_case", "推进治理案件", True),
    ("list_governance_cases", "查看治理案件", False),
    ("governance_ban", "治理禁言", True),
    ("governance_kick", "治理放逐", True),
]


def _group_message_event(
    text: str,
    *,
    user_id: int = 10001,
    group_id: int = 9527,
    role: str = "member",
    message_id: int = 1,
) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1,
        self_id=114514,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        group_id=group_id,
        message_id=message_id,
        message=Message(text),
        raw_message=text,
        font=0,
        sender={
            "user_id": user_id,
            "nickname": f"U{user_id}",
            "card": "",
            "role": role,
            "title": "",
        },
    )


def _write_transcript(name: str, title: str, records: list[dict[str, object]]) -> None:
    _TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _TRANSCRIPT_DIR / f"{name}.md"
    jsonl_path = _TRANSCRIPT_DIR / f"{name}.jsonl"

    if name not in _TRANSCRIPT_INITIALIZED:
        md_path.write_text(f"# {title}\n\n", encoding="utf-8")
        jsonl_path.write_text("", encoding="utf-8")
        _TRANSCRIPT_INITIALIZED.add(name)
        _TRANSCRIPT_SEQUENCES[name] = 0

    md_lines: list[str] = []
    json_lines: list[str] = []
    for record in records:
        _TRANSCRIPT_SEQUENCES[name] += 1
        seq = _TRANSCRIPT_SEQUENCES[name]
        entry = {"seq": seq, **record}
        json_lines.append(json.dumps(entry, ensure_ascii=False))

        role = str(record.get("role") or "system")
        if role == "user":
            user_id = record.get("user_id")
            md_lines.append(f"- `{seq:03d}` 用户 `{user_id}`：`{record.get('text', '')}`")
        else:
            action = record.get("action")
            arg = record.get("arg")
            arg_text = f"，参数 `{arg}`" if arg not in (None, "") else ""
            md_lines.append(f"- `{seq:03d}` 系统：分发到 `{action}`{arg_text}")

    with md_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(md_lines) + "\n")
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(json_lines) + "\n")


def _vote_service_command_cases() -> list[object]:
    return [
        pytest.param(action, command, need_arg, id=f"{command}->{action}")
        for action, command, need_arg in _VOTE_SERVICE_COMMANDS
    ]


def _provider_matchers(provider) -> list[type]:
    return [matcher for matchers in provider.values() for matcher in matchers]


def _ensure_onebot_adapter_registered() -> None:
    import nonebot

    driver = nonebot.get_driver()
    adapters = getattr(driver, "_adapters", {})
    if Adapter.get_name() not in adapters:
        driver.register_adapter(Adapter)


@contextmanager
def _registered_vote_command(app: App, action: str) -> Iterator[type]:
    _ensure_onebot_adapter_registered()

    from src.services import registry
    from src.services.vote import VoteService
    from src.support.core import Services

    method = getattr(VoteService, action)
    meta = registry._resolve_service_action_meta(VoteService, action, method)
    assert meta is not None

    with app.provider.context({}):
        before = set(_provider_matchers(app.provider))
        registry._register_command(Services.Vote, action, meta)
        after = _provider_matchers(app.provider)
        created = [matcher for matcher in after if matcher not in before]
        assert len(created) == 1
        yield created[0]


@pytest.mark.parametrize(("action", "command", "need_arg"), _vote_service_command_cases())
async def test_vote_service_commands_dispatch_from_onebot_group_message(
    app: App,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    command: str,
    need_arg: bool,
) -> None:
    _ensure_onebot_adapter_registered()

    from src.services import registry
    from src.support.core import Services

    calls = []

    async def fake_run_service(**kwargs):
        calls.append(kwargs)
        return {"status": True}

    monkeypatch.setattr(registry, "run_service", fake_run_service)

    raw_arg = "测试参数"
    message_text = f"/{command} {raw_arg}" if need_arg else f"/{command}"

    with _registered_vote_command(app, action) as matcher:
        async with app.test_matcher(matcher) as ctx:
            bot = ctx.create_bot(
                base=Bot,
                adapter=ctx.create_adapter(base=Adapter),
                self_id="114514",
            )
            ctx.receive_event(bot, _group_message_event(message_text))
            ctx.should_pass_rule(matcher)

    assert len(calls) == 1
    call = calls[0]
    assert call["group_id"] == 9527
    assert call["service_enum"] is Services.Vote
    assert call["action"] == action
    assert call["event"].user_id == 10001
    if need_arg:
        assert call["arg"].extract_plain_text().strip() == raw_arg
    else:
        assert "arg" not in call

    _write_transcript(
        "vote_service_command_dispatch",
        "VoteService NoneBug 命令分发记录",
        [
            {
                "role": "user",
                "group_id": call["group_id"],
                "user_id": call["event"].user_id,
                "text": message_text,
            },
            {
                "role": "system",
                "group_id": call["group_id"],
                "action": f"VoteService.{action}",
                "command": command,
                "arg": raw_arg if need_arg else "",
            },
        ],
    )


async def test_support_signatures_can_be_simulated_with_distinct_user_ids(
    app: App,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_onebot_adapter_registered()

    from src.services import registry

    calls = []

    async def fake_run_service(**kwargs):
        calls.append(kwargs)
        return {"status": True}

    monkeypatch.setattr(registry, "run_service", fake_run_service)

    with _registered_vote_command(app, "support_governance_case") as matcher:
        async with app.test_matcher(matcher) as ctx:
            bot = ctx.create_bot(
                base=Bot,
                adapter=ctx.create_adapter(base=Adapter),
                self_id="114514",
            )
            for index, user_id in enumerate(range(20001, 20008), start=1):
                ctx.receive_event(
                    bot,
                    _group_message_event(
                        "/联署治理案件 42",
                        user_id=user_id,
                        message_id=index,
                    ),
                )
                ctx.should_pass_rule(matcher)

    assert [call["event"].user_id for call in calls] == list(range(20001, 20008))
    assert {call["arg"].extract_plain_text().strip() for call in calls} == {"42"}
    assert {call["action"] for call in calls} == {"support_governance_case"}

    records: list[dict[str, object]] = []
    for call in calls:
        records.extend(
            [
                {
                    "role": "user",
                    "group_id": call["group_id"],
                    "user_id": call["event"].user_id,
                    "text": "/联署治理案件 42",
                },
                {
                    "role": "system",
                    "group_id": call["group_id"],
                    "action": "VoteService.support_governance_case",
                    "command": "联署治理案件",
                    "arg": "42",
                },
            ]
        )
    _write_transcript(
        "support_7_signatures",
        "7 人联署模拟记录",
        records,
    )
