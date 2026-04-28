import os
from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


BASE_DIR = Path(__file__).resolve().parent


def _strip_env_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    chars = []

    for char in value:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if not chars or chars[-1].isspace():
                break
        chars.append(char)

    return "".join(chars).strip()


def _parse_env_line(raw_line: str) -> tuple[str | None, str | None]:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None, None

    if line.startswith("export "):
        line = line[7:].strip()

    if "=" not in line:
        return None, None

    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None, None

    value = _strip_env_inline_comment(value.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]

    return key, value


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        key, value = _parse_env_line(raw_line)
        if key and key not in os.environ and value is not None:
            os.environ[key] = value


def _load_runtime_env() -> None:
    _load_env_file(BASE_DIR / ".env")
    environment = (os.getenv("ENVIRONMENT") or "dev").strip()
    if environment:
        _load_env_file(BASE_DIR / f".env.{environment}")
    os.environ.setdefault("LOCALSTORE_USE_CWD", "True")


_load_runtime_env()
os.chdir(BASE_DIR)
nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)
nonebot.load_from_toml("pyproject.toml")
import src.app  # noqa: F401
app = nonebot.get_asgi()

if __name__ == "__main__":
    nonebot.run()
