"""群规与 FAQ 文档检索。"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List

from src.support.core import ToolDefinition, tool_registry


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "laws"


@dataclass(frozen=True)
class LawDoc:
    key: str
    label: str
    path: Path


@dataclass(frozen=True)
class LawBlock:
    source: str
    source_label: str
    title: str
    body: str
    context: str = ""


@dataclass(frozen=True)
class LawOriginalSection:
    title: str
    content: str


LAW_DOCS = {
    "laws": LawDoc("laws", "群规正文", DOCS_DIR / "laws.md"),
    "faq": LawDoc("faq", "FAQ", DOCS_DIR / "群规FAQ.md"),
}

ARTICLE_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零〇两\d]+条(?:之[一二三四五六七八九十百千万零〇两\d]+)?")
HEADING_PATTERN = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
KNOWN_TERMS = (
    "荣誉群主",
    "平台管理员",
    "管理员身份",
    "技术保管人",
    "群主机器人",
    "机器人",
    "元老会",
    "表决权成员",
    "全体表决权成员",
    "高风险权力",
    "高风险操作",
    "紧急防护",
    "紧急防护程序",
    "紧急动议",
    "紧急程序",
    "紧急状态",
    "紧急代理",
    "紧急措施",
    "弹劾",
    "冻结",
    "罢免",
    "踢出",
    "移出群聊",
    "禁言",
    "处分",
    "正式处分",
    "复核",
    "申辩",
    "匿名投票",
    "审计",
    "活跃确认",
    "选民名册",
    "争议票",
    "小号",
    "重组",
    "群迁移",
    "安全模式",
    "提案",
    "联署",
    "换届",
    "候选人",
)
STOP_WORDS = (
    "群规",
    "faq",
    "FAQ",
    "查询",
    "查找",
    "查看",
    "查",
    "依据",
    "条文",
    "规定",
    "内容",
    "请问",
    "一下",
    "关于",
    "这个",
    "那个",
    "什么",
    "怎么",
    "怎么办",
    "是否",
    "能否",
    "能不能",
    "可以",
    "应该",
    "需要",
    "如果",
)

_TOOLS_REGISTERED = False


def _read_doc(doc: LawDoc) -> str:
    if not doc.path.exists():
        return ""
    return doc.path.read_text(encoding="utf-8-sig")


def _split_markdown_blocks(doc: LawDoc) -> List[LawBlock]:
    text = _read_doc(doc)
    if not text:
        return []

    blocks: List[LawBlock] = []
    current_title = ""
    current_lines: List[str] = []
    current_context = ""
    heading_stack: Dict[int, str] = {}

    def flush() -> None:
        nonlocal current_title, current_lines, current_context
        title = current_title.strip()
        body = "\n".join(current_lines).strip()
        if title and body:
            blocks.append(LawBlock(doc.key, doc.label, title, body, current_context))
        current_title = ""
        current_lines = []
        current_context = ""

    for line in text.splitlines():
        heading = HEADING_PATTERN.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            current_title = heading.group(2).strip()
            current_context = "\n".join(
                heading_stack[key] for key in sorted(heading_stack) if key < level
            )
            current_lines = []
            heading_stack = {
                key: value for key, value in heading_stack.items() if key < level
            }
            heading_stack[level] = current_title
            continue
        if current_title:
            current_lines.append(line)

    flush()
    return blocks


def _iter_blocks(source: str = "all") -> List[LawBlock]:
    source = (source or "all").lower()
    docs = LAW_DOCS.values() if source == "all" else [LAW_DOCS[source]] if source in LAW_DOCS else []
    blocks: List[LawBlock] = []
    for doc in docs:
        blocks.extend(_split_markdown_blocks(doc))
    return blocks


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def _is_chinese_text(text: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]+", text))


def _char_ngrams(text: str, size: int = 2) -> set[str]:
    compact = _normalize_text(text)
    if len(compact) < size:
        return set()
    return {compact[index : index + size] for index in range(0, len(compact) - size + 1)}


def _fuzzy_known_terms(query: str) -> List[str]:
    chunks = [
        chunk
        for chunk in re.findall(r"[\u4e00-\u9fff]+", str(query or ""))
        if len(chunk) >= 3
    ]
    terms: List[str] = []

    for chunk in chunks:
        for known_term in KNOWN_TERMS:
            normalized_term = _normalize_text(known_term)
            if len(normalized_term) < 3 or not _is_chinese_text(normalized_term):
                continue
            ratio = SequenceMatcher(None, chunk, normalized_term).ratio()
            common_chars = set(chunk) & set(normalized_term)
            if ratio < 0.72 or len(common_chars) < 3:
                continue
            terms.append(known_term.lower())
            for nested_term in KNOWN_TERMS:
                if nested_term != known_term and nested_term in known_term:
                    terms.append(nested_term.lower())

    return terms


def _query_terms(query: str) -> List[str]:
    cleaned = str(query or "")
    for word in STOP_WORDS:
        cleaned = cleaned.replace(word, " ")

    terms: List[str] = []
    for term in KNOWN_TERMS:
        if term in query:
            terms.append(term.lower())
    terms.extend(_fuzzy_known_terms(query))

    for chunk in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", cleaned.lower()):
        if len(chunk) <= 1:
            continue
        terms.append(chunk)

    seen = set()
    result: List[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def _fuzzy_score(block: LawBlock, query: str) -> int:
    compact_query = _normalize_text(query)
    if len(compact_query) < 4:
        return 0

    compact_title = _normalize_text(block.title)
    title_ratio = SequenceMatcher(None, compact_query, compact_title).ratio() if compact_title else 0

    query_bigrams = _char_ngrams(compact_query, size=2)
    if len(query_bigrams) < 2:
        return int(title_ratio * 10)

    joined = _normalize_text(f"{block.title}\n{block.context}")
    joined_bigrams = _char_ngrams(joined, size=2)
    overlap = len(query_bigrams & joined_bigrams)
    overlap_ratio = overlap / len(query_bigrams)

    score = 0
    if title_ratio >= 0.42:
        score += int(title_ratio * 20)
    if overlap >= 3 and overlap_ratio >= 0.5:
        score += min(overlap * 4, 24)
    return score


def _score_block(block: LawBlock, query: str) -> int:
    title = block.title.lower()
    body = block.body.lower()
    context = block.context.lower()
    joined = f"{title}\n{context}\n{body}"
    compact_query = _normalize_text(query)
    compact_joined = _normalize_text(joined)

    score = 0
    if compact_query and compact_query in compact_joined:
        score += 20

    for article in ARTICLE_PATTERN.findall(query):
        if article in block.title:
            score += 100
        elif article in block.body:
            score += 60

    for term in _query_terms(query):
        if term in title:
            score += 8
        if term in context:
            score += 5
        if term in body:
            score += 3

    score += _fuzzy_score(block, query)

    if score > 0 and block.source == "laws":
        score += 1
    return score


def _truncate(text: str, max_len: int) -> str:
    normalized = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 1].rstrip() + "…"


def search_law_docs(query: str, source: str = "all", limit: int = 3) -> Dict[str, Any]:
    query = str(query or "").strip()
    source = (source or "all").lower()
    if source not in {"all", "laws", "faq"}:
        source = "all"
    limit = max(1, min(int(limit or 3), 5))

    if not query:
        return {
            "success": False,
            "message": "请输入要查询的关键词，例如：弹劾冻结、管理员身份、第三十五条。",
            "matches": [],
        }

    article_refs = ARTICLE_PATTERN.findall(query)
    exact_article_matches = []
    scored = []
    for block in _iter_blocks(source):
        if article_refs and any(article in block.title for article in article_refs):
            exact_article_matches.append((1000, block))
            continue
        score = _score_block(block, query)
        if score > 0:
            scored.append((score, block))

    if exact_article_matches:
        scored = exact_article_matches
    else:
        scored.sort(key=lambda item: item[0], reverse=True)
    matches = [
        {
            "source": block.source,
            "source_label": block.source_label,
            "title": block.title,
            "excerpt": _truncate(block.body, 520),
            "score": score,
        }
        for score, block in scored[:limit]
    ]

    if not matches:
        return {
            "success": False,
            "message": "未找到明确条文。可尝试：/群规 弹劾冻结、/条文 第三十五条、/FAQ 荣誉群主。",
            "matches": [],
        }

    return {"success": True, "message": "找到相关内容。", "matches": matches}


def format_law_search_response(query: str, source: str = "all", limit: int = 3) -> str:
    result = search_law_docs(query, source=source, limit=limit)
    if not result["success"]:
        return result["message"]

    lines = ["找到以下相关内容："]
    for index, match in enumerate(result["matches"], start=1):
        lines.append(f"{index}. 【{match['source_label']}】{match['title']}")
        lines.append(match["excerpt"])
    lines.append("说明：FAQ 仅作理解辅助，正式执行以 laws.md 正文为准。")
    return "\n\n".join(lines)


def iter_law_original_sections() -> List[LawOriginalSection]:
    text = _read_doc(LAW_DOCS["laws"])
    if not text:
        return []

    sections: List[LawOriginalSection] = []
    preamble_lines: List[str] = []
    current_title = ""
    current_lines: List[str] = []
    appendix_title = ""
    appendix_lines: List[str] = []

    def flush_preamble() -> None:
        nonlocal preamble_lines
        content = "\n".join(preamble_lines).strip()
        if content:
            sections.append(LawOriginalSection("文件说明", content))
        preamble_lines = []

    def flush_article() -> None:
        nonlocal current_title, current_lines
        if not current_title:
            return
        lines = [f"#### {current_title}"]
        body = "\n".join(current_lines).strip()
        if body:
            lines.append(body)
        sections.append(LawOriginalSection(current_title, "\n\n".join(lines).strip()))
        current_title = ""
        current_lines = []

    def flush_appendix() -> None:
        nonlocal appendix_title, appendix_lines
        if not appendix_title:
            return
        content = "\n".join(appendix_lines).strip()
        if content:
            sections.append(LawOriginalSection(appendix_title, content))
        appendix_title = ""
        appendix_lines = []

    for line in text.splitlines():
        if line.startswith("## 附表"):
            flush_preamble()
            flush_article()
            flush_appendix()
            appendix_title = line[3:].strip()
            appendix_lines = [line]
            continue

        if appendix_title:
            appendix_lines.append(line)
            continue

        if line.startswith("## "):
            flush_preamble()
            flush_article()
            title = line[3:].strip()
            sections.append(LawOriginalSection(title, line.strip()))
            continue

        if line.startswith("### "):
            flush_article()
            title = line[4:].strip()
            sections.append(LawOriginalSection(title, line.strip()))
            continue

        if line.startswith("#### "):
            title = line[5:].strip()
            if ARTICLE_PATTERN.search(title):
                flush_article()
                current_title = title
                current_lines = []
                continue

        if current_title:
            current_lines.append(line)
        else:
            preamble_lines.append(line)

    flush_preamble()
    flush_article()
    flush_appendix()
    return sections


def build_law_original_forward_nodes(name: str = "群规原文", uin: str = "0") -> List[Dict[str, Any]]:
    return [
        {
            "type": "node",
            "data": {
                "name": name,
                "uin": str(uin),
                "content": section.content,
            },
        }
        for section in iter_law_original_sections()
    ]


def chunk_law_forward_nodes(
    nodes: List[Dict[str, Any]],
    max_nodes: int = 12,
    max_chars: int = 4000,
) -> List[List[Dict[str, Any]]]:
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_chars = 0

    for node in nodes:
        data = node.get("data") if isinstance(node, dict) else None
        content = data.get("content") if isinstance(data, dict) else ""
        node_chars = len(str(content or ""))
        if current and (len(current) >= max_nodes or current_chars + node_chars > max_chars):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(node)
        current_chars += node_chars

    if current:
        chunks.append(current)
    return chunks


def _split_plain_text(text: str, max_chars: int) -> List[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: List[str] = []
    current = ""
    for line in normalized.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        rest = line
        while len(rest) > max_chars:
            chunks.append(rest[:max_chars].rstrip())
            rest = rest[max_chars:].lstrip()
        current = rest

    if current:
        chunks.append(current)
    return chunks


def chunk_law_original_plain_text(
    nodes: List[Dict[str, Any]],
    max_chars: int = 3000,
) -> List[str]:
    max_chars = max(500, int(max_chars or 3000))
    chunks: List[str] = []
    current = ""

    for node in nodes:
        data = node.get("data") if isinstance(node, dict) else None
        content = data.get("content") if isinstance(data, dict) else ""
        for piece in _split_plain_text(content, max_chars):
            candidate = piece if not current else f"{current}\n\n{piece}"
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate

    if current:
        chunks.append(current)
    return chunks


async def _query_law_docs_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    query = str((args or {}).get("query") or "").strip()
    source = str((args or {}).get("source") or "all").strip().lower()
    limit = int((args or {}).get("limit") or 3)
    result = search_law_docs(query, source=source, limit=limit)
    return {
        "success": result["success"],
        "message": result["message"],
        "data": {
            "answer": format_law_search_response(query, source=source, limit=limit),
            "matches": result["matches"],
        },
    }


def register_law_doc_tools() -> None:
    global _TOOLS_REGISTERED
    if _TOOLS_REGISTERED:
        return

    tool_registry.register(
        ToolDefinition(
            name="query_law_docs",
            description="按需查询群规正文 laws.md 或群规 FAQ，用于回答群规、弹劾、投票、处分、权限冻结等问题。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要查询的关键词、条文号或自然语言问题。",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["all", "laws", "faq"],
                        "description": "查询范围：all 同时查正文和 FAQ，laws 只查正文，faq 只查 FAQ。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量，默认 3，最多 5。",
                    },
                },
                "required": ["query"],
            },
            handler=_query_law_docs_tool,
            category="query",
            triggers=["群规", "FAQ", "条文", "依据"],
            gate={
                "pre_route_priority": 100,
                "pre_user_patterns": [
                    r"(群规|群宪法|FAQ|faq|laws|条文)",
                    r"第[一二三四五六七八九十百千万零〇两\d]+条(?:之[一二三四五六七八九十百千万零〇两\d]+)?",
                    r"(投票|表决|选举|弹劾|处分|禁言|移出|踢出|权限|冻结|元老会|荣誉群主|紧急防护|紧急护理|重组|联署|候选|选民名册|复核).{0,16}(是什么|什么意思|怎么|如何|流程|程序|规定|规则|条文|依据|要求|能不能|可以吗|怎么办)",
                    r"(是什么|什么意思|怎么|如何|流程|程序|规定|规则|条文|依据|要求|能不能|可以吗|怎么办).{0,16}(投票|表决|选举|弹劾|处分|禁言|移出|踢出|权限|冻结|元老会|荣誉群主|紧急防护|紧急护理|重组|联署|候选|选民名册|复核)",
                    r"(条例|依据|规定|规则).{0,12}(哪条|哪一条|条文|流程|程序|要求)",
                ],
                "user_keywords": [
                    "群规",
                    "群宪法",
                    "条例",
                    "FAQ",
                    "条文",
                    "依据",
                    "投票",
                    "表决",
                    "选举",
                    "弹劾",
                    "处分",
                    "禁言",
                    "移出",
                    "踢出",
                    "权限",
                    "冻结",
                    "元老会",
                    "荣誉群主",
                    "紧急",
                    "紧急防护",
                    "紧急护理",
                    "重组",
                    "联署",
                    "候选",
                    "选民名册",
                    "复核",
                ],
                "assistant_keywords": [
                    "群规",
                    "群宪法",
                    "条例",
                    "FAQ",
                    "条文",
                    "依据",
                    "投票",
                    "表决",
                    "选举",
                    "弹劾",
                    "处分",
                    "禁言",
                    "移出",
                    "踢出",
                    "权限",
                    "冻结",
                    "元老会",
                    "荣誉群主",
                    "紧急",
                    "重组",
                    "联署",
                    "候选",
                    "复核",
                    "查询",
                    "检索",
                    "找不到",
                    "没找到",
                    "未找到",
                    "无法找到",
                    "无法确认",
                    "不确定",
                    "不知道",
                    "不清楚",
                ],
                "system_prompt": "检测到用户正在询问群规、条例或 FAQ，但助手未先检索资料。必须调用 query_law_docs 查询 laws.md 或 FAQ 后再回答；即使用户有错别字，也应先尝试模糊检索，禁止直接凭空回答或直接说找不到。",
            },
        )
    )
    _TOOLS_REGISTERED = True


__all__ = [
    "build_law_original_forward_nodes",
    "chunk_law_forward_nodes",
    "chunk_law_original_plain_text",
    "format_law_search_response",
    "iter_law_original_sections",
    "register_law_doc_tools",
    "search_law_docs",
]
