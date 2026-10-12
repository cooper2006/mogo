"""Docling 解析链路测试。

这些测试专门覆盖 ``app.services.document_parsing_service`` 中依赖 docling /
transformers / onnxruntime 的解析与切分路径——即上一轮回归中标记为
"未被 3.13 pytest 覆盖"的缺口。

设计约束：
- 通过 ``importorskip("docling")`` 保护：在没有安装 docling 的普通开发
  venv / CI venv 中自动跳过（与仓库既有设计一致——``requirements-docling.txt``
  只在 Docker 镜像内安装，见 ``quality-gate.yml`` 注释）。
- 在已安装 docling 的容器内（生产环境：3.13 + transformers 5.10.0 +
  ``/opt/docling/models`` 离线模型）真实触发 ``DocumentConverter().convert()``
  → ``export_to_markdown`` → ``HybridChunker`` 全链路，零联网、零版本差异。
- docling 重型模块（``document_converter``、``HybridChunker``、新路径
  ``docling_core.transforms.chunker.tokenizer.base.BaseTokenizer``）均为
  运行时延迟导入，这里正是要验证这些路径在 3.13 下可用。
"""

import pytest

docling = pytest.importorskip("docling")


def test_parse_document_txt_runs_docling_pipeline(tmp_path):
    """parse_document 对纯文本走 docling 真实转换 + 切分全链路。"""
    from app.services.document_parsing_service import parse_document

    sample = tmp_path / "sample.txt"
    sample.write_text(
        "# 标题\n\n这是一段中文测试文本，用于验证 docling 在 3.13 下的离线解析链路。\n"
        "第二段内容用于触发 HybridChunker 的切分逻辑。\n",
        encoding="utf-8",
    )

    parsed = parse_document(sample, "sample.txt")

    # docling 真实转换产出了 markdown
    assert isinstance(parsed.markdown, str)
    assert parsed.markdown.strip(), "docling 未导出 markdown"
    assert "标题" in parsed.markdown

    # raw 是 docling 的 DoclingDocument schema 导出（非回退路径）
    assert parsed.raw.get("schema_name") == "DoclingDocument"

    # HybridChunker 切分产出了 chunk，且 metadata 标记来自 docling 解析器
    assert parsed.raw_chunks, "docling 文档未被 HybridChunker 切分"
    for chunk in parsed.raw_chunks:
        assert chunk["metadata"]["parser"] == "docling"
        assert chunk["metadata"]["chunker"] == "HybridChunker"
        assert "text" in chunk and chunk["text"].strip()


def test_chunk_docling_document_structure(tmp_path):
    """直接验证 chunk_docling_document 对 docling Document 的切分结构。"""
    from docling.document_converter import DocumentConverter

    from app.services.document_parsing_service import chunk_docling_document

    sample = tmp_path / "chunk_src.txt"
    sample.write_text(
        "段落一：用于切分的样例文本。\n\n段落二：第二段样例文本，验证 chunk 顺序与元数据。\n",
        encoding="utf-8",
    )

    document = DocumentConverter().convert(str(sample)).document
    chunks = chunk_docling_document(document)

    assert chunks, "docling 文档切分结果为空"
    # ordinate/chunkId 连续且结构正确
    for idx, chunk in enumerate(chunks):
        assert chunk["ordinal"] == idx
        assert chunk["chunkId"] == f"raw_{idx + 1:06d}"
        assert chunk["metadata"]["tokenizer"] == "AskAILocalTokenizer"
        assert chunk["metadata"]["doclingMeta"] is not None


def test_docling_base_tokenizer_new_path_importable():
    """验证 docling 3.15 重构后的 BaseTokenizer 导入路径（上一轮已知差异点）。"""
    from docling.chunking import HybridChunker  # noqa: F401
    from docling_core.transforms.chunker.tokenizer.base import (  # noqa: F401
        BaseTokenizer,
    )

    assert True  # 导入成功即证明新路径在 3.13 下可用


def test_parse_document_txt_imports_docling_heavy_modules(tmp_path):
    """parse_document 在 docling 可用时不应回退到 fallback。"""
    import sys

    from app.services.document_parsing_service import parse_document

    sample = tmp_path / "heavy.txt"
    sample.write_text("验证 docling 重型模块被真实加载而非回退。\n", encoding="utf-8")

    # 若 docling 缺失，parse_document 会走 parse_with_fallback；此处 docling 已装，
    # 故 raw 应为 DoclingDocument schema 导出（非回退路径），证明重型路径被触发。
    parsed = parse_document(sample, "heavy.txt")
    assert parsed.raw.get("schema_name") == "DoclingDocument"
    # 同时确认 docling 重型模块确实在解释器内可用
    assert "docling.document_converter" in sys.modules
