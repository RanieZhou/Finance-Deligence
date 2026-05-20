"""
完整流水线入口：PDF → DocumentResult JSON
"""
from __future__ import annotations
import json
from pathlib import Path
from loguru import logger

from pipeline.parser.mineru_parser import parse_pdf
from pipeline.structure.toc_parser import build_structure
from pipeline.structure.table_stitcher import stitch_tables
from pipeline.structure.block_classifier import classify_blocks, filter_noise
from pipeline.router.section_router import route_blocks
from pipeline.extractor.field_extractor import (
    extract_issuer, extract_ownership, extract_financials,
    extract_fund_raising, extract_risks, extract_compliance,
)
from pipeline.validator.post_processor import (
    normalize_document, validate_document, build_evidence_index,
)
from schemas.models import DocumentResult


def run_pipeline(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    mineru_cache_dir: str | Path | None = None,
    parse_mode: str = "txt",    # txt=快速（本地CPU），auto=全模型（GPU服务器）
) -> DocumentResult:
    """
    端到端流水线。
    mineru_cache_dir: 若已有 MinerU 解析缓存，直接读取跳过重新解析。
    """
    pdf_path = Path(pdf_path)
    doc_id = pdf_path.stem

    # ── Layer 1: MinerU 解析 ──────────────────────────────
    logger.info(f"[{doc_id}] Layer 1: Parsing PDF")
    parsed = parse_pdf(pdf_path, output_dir=mineru_cache_dir, mode=parse_mode)

    # ── Layer 2: 结构恢复 ─────────────────────────────────
    logger.info(f"[{doc_id}] Layer 2: Structure recovery")
    # 2a. 跨页表格拼接
    stitched_blocks = stitch_tables(parsed)
    # 2b. 过滤页眉/页脚/页码
    classified = classify_blocks(stitched_blocks)
    clean_blocks = filter_noise(classified)
    # 2c. 目录解析 + block→chapter 映射
    from pipeline.parser.mineru_parser import ParsedDocument
    clean_doc = ParsedDocument(
        pdf_path=parsed.pdf_path,
        blocks=clean_blocks,
        total_pages=parsed.total_pages,
    )
    structure = build_structure(clean_doc)
    logger.info(f"[{doc_id}] TOC nodes: {len(structure.toc)}, "
                f"Mapped blocks: {len(structure.block_chapter_map)}")

    # ── Layer 3: 章节路由 ─────────────────────────────────
    logger.info(f"[{doc_id}] Layer 3: Section routing")
    section_map = route_blocks(clean_blocks, structure)
    for target, chunks in section_map.items():
        logger.info(f"  {target}: {len(chunks)} chunks")

    # 若发行人无章节匹配，降级为全文 fallback（短公告/无标准目录文档）
    if not section_map["issuer_profile"]:
        from pipeline.router.section_router import SectionChunk
        full_text = "\n\n".join(
            f"[p{b.page_no}] {b.text}"
            for b in clean_blocks if b.block_type in ("text", "table")
        )[:12000]
        if full_text:
            section_map["issuer_profile"] = [
                SectionChunk(target="issuer_profile", chapter="全文", text=full_text)
            ]
            logger.info(f"[{doc_id}] issuer_profile fallback: 全文 {len(full_text)} chars")

    # ── Layer 4: LLM 抽取 ─────────────────────────────────
    logger.info(f"[{doc_id}] Layer 4: LLM extraction")

    # 4a. 规则抽取：财务报表表格直接解析（快速、无幻觉）
    from pipeline.structure.financial_table_parser import extract_table_financials, merge_financials
    table_financials = extract_table_financials(clean_blocks, structure)
    logger.info(f"[{doc_id}] Table parser: {len(table_financials)} financial records")

    # 4b. LLM 抽取
    doc = DocumentResult(
        document_id=doc_id,
        document_type=_detect_doc_type(pdf_path.name),
    )
    doc.issuer_profile        = extract_issuer(section_map["issuer_profile"])
    doc.ownership_structure   = extract_ownership(section_map["ownership_structure"])
    llm_financials            = extract_financials(section_map["financials"])
    doc.fund_raising_projects = extract_fund_raising(section_map["fund_raising_projects"])
    doc.risk_items            = extract_risks(section_map["risk_items"])
    doc.compliance_items      = extract_compliance(section_map["compliance_items"])

    # 4c. 合并财务指标：规则结果优先，LLM 补充
    doc.financials = merge_financials(table_financials, llm_financials)
    logger.info(f"[{doc_id}] Financials merged: {len(doc.financials)} records total")

    # ── Layer 5: 后处理 ───────────────────────────────────
    logger.info(f"[{doc_id}] Layer 5: Post-processing")
    doc = normalize_document(doc)
    warnings = validate_document(doc)
    doc.evidence_index = build_evidence_index(doc)

    # ── 输出 ──────────────────────────────────────────────
    if output_dir:
        out = Path(output_dir) / f"{doc_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(doc.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"[{doc_id}] Saved → {out}")

    logger.info(f"[{doc_id}] Done. warnings={len(warnings)}")
    return doc


def _detect_doc_type(filename: str) -> str:
    """根据文件名推断文档类型"""
    fname = filename.upper()
    if "招股" in fname or "IPO" in fname:
        return "招股说明书"
    if "可转债" in fname or "CB" in fname:
        return "可转债募集说明书"
    if "上市公告" in fname:
        return "上市公告书"
    if "补充" in fname or "RAS" in fname:
        return "补充披露文件"
    return "招股说明书"  # 默认
