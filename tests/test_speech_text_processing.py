from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.support.core import process_text


def test_process_text_for_speech_strips_markdown_symbols_and_emoji() -> None:
    raw = "## 标题\n**呜呜**，/// `只想唱给你听` ❤️"

    result = process_text(raw, for_speech=True)

    assert result == "标题 呜呜，只想唱给你听"


def test_process_text_for_speech_removes_escape_like_symbols_without_dropping_content() -> None:
    raw = r"Omega\反斜杠/// 不过如果是你的话 _喵_ ❤️"

    result = process_text(raw, for_speech=True)

    assert "\\" not in result
    assert "/" not in result
    assert "❤️" not in result
    assert "Omega" in result
    assert "不过如果是你的话" in result
    assert "喵" in result


def test_process_text_for_speech_returns_empty_for_pure_decorative_input() -> None:
    raw = "/// \\\\ ❤️ ✨"

    assert process_text(raw, for_speech=True) == ""
