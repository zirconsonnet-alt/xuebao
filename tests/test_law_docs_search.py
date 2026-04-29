from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services._ai.tool_runtime import AIAssistantToolRuntimeMixin
from src.support.core import gate_hit, tool_registry
from src.support.law_docs import (
    build_law_document_forward_nodes,
    chunk_law_original_plain_text,
    register_law_doc_tools,
    search_law_docs,
)


def test_law_search_handles_chinese_typo_with_fuzzy_terms():
    result = search_law_docs("紧急护理程序", source="all", limit=5)

    assert result["success"] is True
    titles = [match["title"] for match in result["matches"]]
    assert any("第十三条" in title or "紧急状态" in title for title in titles)


def test_law_search_does_not_force_match_unrelated_noise():
    result = search_law_docs("完全不存在的乱码xyz", source="all", limit=3)

    assert result["success"] is False
    assert result["matches"] == []


def test_law_doc_tool_gate_catches_law_lookup_without_tool_call():
    register_law_doc_tools()
    tool = tool_registry.get_tool("query_law_docs")

    assert tool is not None
    assert tool.gate is not None
    assert gate_hit(tool.gate, "紧急护理程序是什么", "我没有找到紧急护理程序的相关条文")
    assert not gate_hit(tool.gate, "今天吃什么", "可以吃点清淡的")


def test_law_doc_tool_pre_route_catches_high_confidence_lookup():
    register_law_doc_tools()
    assistant = AIAssistantToolRuntimeMixin()

    tool = assistant._select_preferred_tool_for_user("紧急护理程序是什么", exclude_categories=[])

    assert tool is not None
    assert tool.name == "query_law_docs"
    assert assistant._select_preferred_tool_for_user("今天吃什么", exclude_categories=[]) is None
    assert assistant._select_preferred_tool_for_user("这个依据是什么", exclude_categories=[]) is None


def test_law_original_plain_text_chunks_have_size_limit():
    nodes = [
        {
            "type": "node",
            "data": {
                "content": "第一段\n" + "甲" * 520,
            },
        },
        {
            "type": "node",
            "data": {
                "content": "第二段\n" + "乙" * 520,
            },
        },
    ]

    chunks = chunk_law_original_plain_text(nodes, max_chars=500)

    assert chunks
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "第一段" in chunks[0]


def test_law_public_documents_can_build_forward_nodes():
    for key, expected in (("laws", "群宪法及治理条例"), ("brief", "简明群规"), ("faq", "群规 FAQ")):
        nodes = build_law_document_forward_nodes(key, name=expected, uin="0")

        assert nodes
        contents = "\n".join(str(node["data"]["content"]) for node in nodes)
        assert expected in contents
