"""
Vendored package ownership registry.

Every importable package under `src/vendors` must have an explicit owner
module under `src.services`.
"""

from dataclasses import dataclass
import importlib.util
from pathlib import Path


@dataclass(frozen=True)
class VendorOwner:
    owner_module: str
    owner_file: str
    notes: str = ""


VENDOR_PLUGIN_OWNERS: dict[str, VendorOwner] = {
    "nonebot_bison": VendorOwner(
        owner_module="src.services.bison",
        owner_file="src/services/bison.py",
        notes="Bison runtime owner",
    ),
    "nonebot_plugin_batarot": VendorOwner(
        owner_module="src.services.tarot",
        owner_file="src/services/tarot.py",
        notes="Tarot service facade",
    ),
    "nonebot_plugin_dialectlist": VendorOwner(
        owner_module="src.services.dialectlist",
        owner_file="src/services/dialectlist.py",
        notes="Dialectlist service facade",
    ),
    "nonebot_plugin_auto_emojimix": VendorOwner(
        owner_module="src.services.emojimix",
        owner_file="src/services/emojimix.py",
        notes="Emojimix service facade",
    ),
    "nonebot_plugin_math_game": VendorOwner(
        owner_module="src.services.math_game",
        owner_file="src/services/math_game.py",
        notes="24-point game service facade",
    ),
    "nonebot_plugin_multincm": VendorOwner(
        owner_module="src.services.multincm",
        owner_file="src/services/multincm.py",
        notes="MultiNCM runtime owner",
    ),
    "nonebot_plugin_resolver": VendorOwner(
        owner_module="src.services.resolver",
        owner_file="src/services/resolver.py",
        notes="Resolver runtime owner",
    ),
    "nonebot_plugin_memes": VendorOwner(
        owner_module="src.services.meme",
        owner_file="src/services/meme.py",
        notes="Meme service facade",
    ),
    "nonebot_plugin_reminder": VendorOwner(
        owner_module="src.services.reminder",
        owner_file="src/services/reminder.py",
        notes="Reminder service facade",
    ),
    "nonebot_plugin_sp": VendorOwner(
        owner_module="src.services.sp",
        owner_file="src/services/sp.py",
        notes="Turtle soup service facade",
    ),
    "nonebot_plugin_werewolf": VendorOwner(
        owner_module="src.services.werewolf",
        owner_file="src/services/werewolf.py",
        notes="Werewolf service facade",
    ),
    "nonebot_plugin_whateat_pic": VendorOwner(
        owner_module="src.services.whateat",
        owner_file="src/services/whateat.py",
        notes="Food recommendation service facade",
    ),
    "nonebot_plugin_law": VendorOwner(
        owner_module="src.services.vote",
        owner_file="src/services/vote.py",
        notes="Vote and governance service facade",
    ),
    "nonebot_plugin_wordcloud": VendorOwner(
        owner_module="src.services.wordcloud",
        owner_file="src/services/wordcloud.py",
        notes="Wordcloud service facade",
    ),
}


def iter_vendor_plugin_dirs(root: str | Path = "src/vendors") -> tuple[str, ...]:
    root_path = Path(root)
    if not root_path.exists():
        return ()
    plugin_names = [
        child.name
        for child in root_path.iterdir()
        if child.is_dir()
        and child.name != "__pycache__"
        and (child / "__init__.py").exists()
    ]
    return tuple(sorted(plugin_names))


def iter_vendor_owner_modules() -> tuple[str, ...]:
    return tuple(sorted({owner.owner_module for owner in VENDOR_PLUGIN_OWNERS.values()}))


def validate_vendor_plugin_ownership(root: str | Path = "src/vendors") -> None:
    plugin_names = set(iter_vendor_plugin_dirs(root))
    owner_names = set(VENDOR_PLUGIN_OWNERS.keys())

    missing = sorted(plugin_names - owner_names)
    extra = sorted(owner_names - plugin_names)

    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"缺少 owner 映射: {', '.join(missing)}")
        if extra:
            details.append(f"存在无效 owner 映射: {', '.join(extra)}")
        raise RuntimeError("; ".join(details))

    errors: list[str] = []
    for plugin_name, owner in sorted(VENDOR_PLUGIN_OWNERS.items()):
        spec = importlib.util.find_spec(owner.owner_module)
        if spec is None:
            errors.append(f"{plugin_name} -> {owner.owner_module}")

    if errors:
        raise RuntimeError("Vendor owner 模块加载失败: " + " | ".join(errors))


__all__ = [
    "VendorOwner",
    "VENDOR_PLUGIN_OWNERS",
    "iter_vendor_owner_modules",
    "iter_vendor_plugin_dirs",
    "validate_vendor_plugin_ownership",
]
