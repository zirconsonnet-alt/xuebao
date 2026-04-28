import argparse
import re
from pathlib import Path

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "skill"

def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        t = line.strip()
        if t:
            return t
    return ""

def derive_name_and_description(md_path: Path, text: str) -> tuple[str, str]:
    base = md_path.stem
    name = slugify(base)
    line = first_nonempty_line(text)
    desc = ""
    if line.startswith("#"):
        desc = line.lstrip("#").strip()
    elif line:
        desc = line.strip()
    if not desc:
        desc = f"BMAD prompt converted from {md_path.name}"
    desc = re.sub(r"\s+", " ", desc).strip()
    if len(desc) > 500:
        desc = desc[:497].rstrip() + "..."
    if len(name) > 100:
        name = name[:100].rstrip("-")
    return name, desc

def build_skill_md(name: str, description: str, body: str) -> str:
    header = f"---\nname: {name}\ndescription: {description}\n---\n"
    body = body.lstrip("\ufeff")
    if not body.endswith("\n"):
        body += "\n"
    return header + "\n" + body

def write_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="replace")
        if old == content:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pattern", default="*.md")
    ap.add_argument("--prefix", default="bmad-")
    args = ap.parse_args()

    prompts_dir = Path(args.prompts).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()

    if not prompts_dir.exists() or not prompts_dir.is_dir():
        raise SystemExit(f"prompts dir not found: {prompts_dir}")

    md_files = sorted(prompts_dir.glob(args.pattern))
    if not md_files:
        raise SystemExit(f"no files matched: {prompts_dir / args.pattern}")

    changed = 0
    total = 0

    for md in md_files:
        text = md.read_text(encoding="utf-8", errors="replace")
        name, desc = derive_name_and_description(md, text)

        if args.prefix and not name.startswith(args.prefix):
            name = args.prefix + name

        skill_dir = out_dir / name
        skill_md_path = skill_dir / "SKILL.md"
        ref_path = skill_dir / "references" / "source.md"

        skill_md = build_skill_md(name, desc, text)

        total += 1
        if write_if_changed(skill_md_path, skill_md):
            changed += 1
        write_if_changed(ref_path, text)

    print(f"converted {total} prompts into skills at: {out_dir}")
    print(f"updated SKILL.md files: {changed}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
