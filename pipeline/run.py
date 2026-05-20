"""
完整流水线入口：PDF → DocumentResult JSON
"""
from __future__ import annotations
import json
import re
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
    normalize_document, validate_document, build_evidence_index, remap_evidence_ids,
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

    # 若发行人无章节匹配，降级为关键词搜索 fallback
    if not section_map["issuer_profile"]:
        from pipeline.router.section_router import SectionChunk
        _ISSUER_KW = re.compile(
            r'发行人名称|公司全称|公司简称|注册资本|法定代表人|注册地址|成立日期|营业执照|主营业务|经营范围'
        )
        kw_blocks = [
            b for b in clean_blocks
            if b.block_type in ("text", "table") and _ISSUER_KW.search(b.text or "")
        ][:30]  # 最多取前30个命中块，避免上下文溢出
        if kw_blocks:
            kw_text = "\n\n".join(f"[p{b.page_no}] {b.text}" for b in kw_blocks)[:12000]
            section_map["issuer_profile"] = [
                SectionChunk(target="issuer_profile", chapter="发行人基本情况", text=kw_text)
            ]
            logger.info(f"[{doc_id}] issuer_profile fallback: keyword {len(kw_blocks)} blocks")
        else:
            # 兜底：取前20页的非空文本块
            early_blocks = [
                b for b in clean_blocks
                if b.block_type == "text" and b.page_no <= 20
            ]
            early_text = "\n\n".join(f"[p{b.page_no}] {b.text}" for b in early_blocks)[:8000]
            if early_text:
                section_map["issuer_profile"] = [
                    SectionChunk(target="issuer_profile", chapter="全文", text=early_text)
                ]
                logger.info(f"[{doc_id}] issuer_profile fallback: early pages {len(early_text)} chars")

    # 股权控制 fallback：章节路由未命中时，关键词搜索全文
    if not section_map["ownership_structure"]:
        from pipeline.router.section_router import SectionChunk
        _OWNERSHIP_KW = re.compile(
            r'控股股东|实际控制人|持股比例|股权结构|前十大股东|持股情况|一致行动|控制关系|共同控制|夫妻'
        )
        own_blocks = [
            b for b in clean_blocks
            if b.block_type in ("text", "table") and _OWNERSHIP_KW.search(b.text or "")
        ][:30]
        if own_blocks:
            own_text = "\n\n".join(f"[p{b.page_no}] {b.text}" for b in own_blocks)[:12000]
            section_map["ownership_structure"] = [
                SectionChunk(target="ownership_structure", chapter="股权结构", text=own_text)
            ]
            logger.info(f"[{doc_id}] ownership_structure fallback: keyword {len(own_blocks)} blocks")

    # 合规事项 fallback：章节路由未命中时，关键词搜索全文
    if not section_map["compliance_items"]:
        from pipeline.router.section_router import SectionChunk
        _COMPLIANCE_KW = re.compile(
            r'对外担保|诉讼|仲裁|关联交易|行政处罚|违规|重大合同|承诺事项|或有负债|重大事项'
        )
        cpl_blocks = [
            b for b in clean_blocks
            if b.block_type == "text" and _COMPLIANCE_KW.search(b.text or "")
        ][:40]
        if cpl_blocks:
            cpl_text = "\n\n".join(f"[p{b.page_no}] {b.text}" for b in cpl_blocks)[:16000]
            section_map["compliance_items"] = [
                SectionChunk(target="compliance_items", chapter="重大事项", text=cpl_text)
            ]
            logger.info(f"[{doc_id}] compliance_items fallback: keyword {len(cpl_blocks)} blocks")

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
    logger.info(f"[{doc_id}] Financials merged: {len(doc.financials)} total")

    # ── Layer 5: 后处理 ───────────────────────────────────
    logger.info(f"[{doc_id}] Layer 5: Post-processing")
    doc = normalize_document(doc)
    warnings = validate_document(doc)
    doc.evidence_index = build_evidence_index(doc)
    doc = remap_evidence_ids(doc)

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
