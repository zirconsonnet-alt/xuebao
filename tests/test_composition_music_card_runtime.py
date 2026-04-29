import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class DummyGateway:
    def __init__(self, *, fail_upload_groups: set[int] | None = None):
        self.fail_upload_groups = set(fail_upload_groups or set())
        self.files_by_group: dict[int, list[dict]] = {}
        self.upload_attempts: list[tuple[int, str, str, str]] = []

    async def get_group_root_files(self, group_id: int):
        return {"files": list(self.files_by_group.get(group_id, []))}

    async def upload_file(self, group_id: int, path: str, name: str, folder_id: str):
        self.upload_attempts.append((group_id, Path(path).name, name, folder_id))
        if group_id in self.fail_upload_groups:
            raise RuntimeError(f"group {group_id} upload failed")
        self.files_by_group.setdefault(group_id, [])
        self.files_by_group[group_id].insert(
            0,
            {
                "file_id": f"{group_id}-{name}",
                "busid": 1,
                "file_name": name,
            },
        )

    async def get_group_file_url(self, group_id: int, file_id: str, busid: int):
        return {"url": f"https://example.com/{group_id}/{file_id}"}


class DummyGroup:
    def __init__(
        self,
        tmp_path: Path,
        gateway: DummyGateway,
        *,
        uploaded_files: list[dict] | None = None,
        direct_name: str | None = None,
        direct_url: str | None = None,
    ):
        self.group_id = 123
        self.gateway = gateway
        self.group_path = tmp_path / "group"
        self.temp_path = self.group_path / "temp"
        self.group_path.mkdir(parents=True, exist_ok=True)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        self._uploaded_files = list(uploaded_files or [])
        self._direct_name = direct_name
        self._direct_url = direct_url

    async def get_user_img(self, user_id: int):
        return f"https://example.com/avatar/{user_id}.jpg"

    async def get_resent_file_url(self):
        if self._direct_name is None or self._direct_url is None:
            raise AssertionError("不应走原始直链分支")
        return self._direct_name, self._direct_url

    async def get_files(self):
        return list(self._uploaded_files)

    async def download_file(self, file_entry: dict):
        save_path = self.temp_path / file_entry["file_name"]
        save_path.write_bytes(b"source-audio")
        return save_path

    async def get_message_history(self, count: int = 20):
        return {"messages": []}


class DummyMatcher:
    def __init__(self):
        self.sent: list[object] = []

    async def send(self, message):
        self.sent.append(message)
        return {"message_id": len(self.sent)}


def _make_service(tmp_path: Path, group: DummyGroup, *, cache_group_id: int = 0):
    from src.services.composition import CompositionService

    service = object.__new__(CompositionService)
    service.group = group
    service.config_file = tmp_path / "composition_service.json"
    service._config = dict(CompositionService.default_config)
    service._config["auto_essence_enabled"] = False
    service._config["music_card_cache_group_id"] = cache_group_id
    service._card_message_map = {}
    return service


def test_composition_music_card_transcodes_flac_and_uploads_to_cache_group(tmp_path: Path, monkeypatch) -> None:
    import src.services.composition as composition_module

    gateway = DummyGateway()
    group = DummyGroup(
        tmp_path,
        gateway,
        uploaded_files=[
            {
                "file_id": "origin-flac",
                "busid": 1,
                "file_name": "作品.flac",
                "uploader": 456,
            }
        ],
    )
    service = _make_service(tmp_path, group, cache_group_id=888)
    matcher = DummyMatcher()
    event = SimpleNamespace(
        user_id=456,
        group_id=123,
        file=SimpleNamespace(name="作品.flac"),
    )

    async def fake_get_name(_event):
        return "测试用户"

    async def fake_convert(source_path: Path, target_path: Path):
        assert source_path.name == "作品.flac"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"converted-mp3")
        return target_path

    monkeypatch.setattr(composition_module, "get_name", fake_get_name)
    monkeypatch.setattr(
        composition_module.CompositionService,
        "_convert_audio_to_mp3",
        staticmethod(fake_convert),
    )

    asyncio.run(service._send_music_card(event, matcher))

    assert gateway.upload_attempts == [
        (888, "origin-flac.mp3", "composition_origin-flac.mp3", "/")
    ]
    assert len(matcher.sent) == 2
    music_card = matcher.sent[0]
    assert getattr(music_card, "type", "") == "music"
    assert music_card.data["audio"] == "https://example.com/888/888-composition_origin-flac.mp3"
    assert music_card.data["title"] == "作品.flac"
    assert "老师发布了新作品" in str(matcher.sent[1])


def test_composition_music_card_falls_back_to_current_group_when_cache_upload_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import src.services.composition as composition_module

    gateway = DummyGateway(fail_upload_groups={888})
    group = DummyGroup(
        tmp_path,
        gateway,
        uploaded_files=[
            {
                "file_id": "origin-m4a",
                "busid": 1,
                "file_name": "作品.m4a",
                "uploader": 456,
            }
        ],
    )
    service = _make_service(tmp_path, group, cache_group_id=888)
    matcher = DummyMatcher()
    event = SimpleNamespace(
        user_id=456,
        group_id=123,
        file=SimpleNamespace(name="作品.m4a"),
    )

    async def fake_get_name(_event):
        return "测试用户"

    async def fake_convert(source_path: Path, target_path: Path):
        assert source_path.name == "作品.m4a"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"converted-mp3")
        return target_path

    monkeypatch.setattr(composition_module, "get_name", fake_get_name)
    monkeypatch.setattr(
        composition_module.CompositionService,
        "_convert_audio_to_mp3",
        staticmethod(fake_convert),
    )

    asyncio.run(service._send_music_card(event, matcher))

    assert gateway.upload_attempts == [
        (888, "origin-m4a.mp3", "composition_origin-m4a.mp3", "/"),
        (123, "origin-m4a.mp3", "composition_origin-m4a.mp3", "/"),
    ]
    music_card = matcher.sent[0]
    assert music_card.data["audio"] == "https://example.com/123/123-composition_origin-m4a.mp3"
    assert music_card.data["title"] == "作品.m4a"


def test_composition_music_card_keeps_direct_url_for_mp3_upload(tmp_path: Path) -> None:
    service = _make_service(
        tmp_path,
        DummyGroup(
            tmp_path,
            DummyGateway(),
            direct_name="作品.mp3",
            direct_url="https://example.com/direct.mp3",
        ),
    )
    event = SimpleNamespace(
        user_id=456,
        group_id=123,
        file=SimpleNamespace(name="作品.mp3"),
    )

    name, audio_url = asyncio.run(service._resolve_music_card_audio(event))

    assert name == "作品.mp3"
    assert audio_url == "https://example.com/direct.mp3"


def test_composition_service_migrates_legacy_supported_formats_to_include_m4a_flac(tmp_path: Path) -> None:
    service = _make_service(tmp_path, DummyGroup(tmp_path, DummyGateway()))
    service._config["supported_formats"] = [".wav", ".mp3"]
    save_calls: list[list[str]] = []

    def fake_save_config():
        save_calls.append(list(service._config["supported_formats"]))

    service._save_config = fake_save_config

    supported_formats = service._ensure_supported_formats_config()

    assert supported_formats == [".wav", ".mp3", ".m4a", ".flac"]
    assert service._config["supported_formats"] == [".wav", ".mp3", ".m4a", ".flac"]
    assert save_calls == [[".wav", ".mp3", ".m4a", ".flac"]]


def test_composition_service_accepts_uppercase_m4a_suffix(tmp_path: Path) -> None:
    service = _make_service(tmp_path, DummyGroup(tmp_path, DummyGateway()))
    matcher = DummyMatcher()
    event = SimpleNamespace(file=SimpleNamespace(name="作品.M4A"))
    sent_events: list[str] = []

    async def fake_send_music_card(current_event, current_matcher):
        assert current_matcher is matcher
        sent_events.append(current_event.file.name)

    service._send_music_card = fake_send_music_card

    asyncio.run(service.on_file_upload(event, matcher))

    assert sent_events == ["作品.M4A"]


def test_composition_service_essence_window_extends_to_24_hours(tmp_path: Path) -> None:
    service = _make_service(tmp_path, DummyGroup(tmp_path, DummyGateway()))

    assert service.CARD_MAP_TTL_SECONDS == 24 * 60 * 60


def test_composition_music_card_refuses_before_downloading_when_storage_guard_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import src.services.composition as composition_module

    group = DummyGroup(
        tmp_path,
        DummyGateway(),
        uploaded_files=[
            {
                "file_id": "origin-flac",
                "busid": 1,
                "file_name": "作品.flac",
                "uploader": 456,
            }
        ],
    )
    service = _make_service(tmp_path, group)
    event = SimpleNamespace(
        user_id=456,
        group_id=123,
        file=SimpleNamespace(name="作品.flac"),
    )

    async def fail_download(_file_entry):
        raise AssertionError("低磁盘时不应下载源音频")

    group.download_file = fail_download
    monkeypatch.setattr(
        composition_module,
        "ensure_optional_write_allowed",
        lambda *args, **kwargs: SimpleNamespace(allowed=False, message="磁盘不足"),
    )

    audio_path, cache_key = asyncio.run(
        service._ensure_transcoded_audio_file(group._uploaded_files[0], event)
    )

    assert audio_path is None
    assert cache_key == "origin-flac"
