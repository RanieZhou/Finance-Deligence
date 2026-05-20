"""
端到端 LLM 抽取测试（跳过 MinerU，使用已缓存的 content_list.json）
用法: cd ~/Desktop/finance-due-diligence && python scripts/test_llm_extract.py
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
logger.remove()
logger.add(sys.stderr, format="{time:HH:mm:ss} {level} {message}", level="INFO")

from pipeline.parser.mineru_parser import _normalize_blocks, ParsedDocument
from pipeline.structure.toc_parser import build_structure
from pipeline.structure.table_stitcher import stitch_tables
from pipeline.structure.block_classifier import classify_blocks, filter_noise
from pipeline.router.section_router import route_blocks
from pipeline.extractor.field_extractor import (
    extract_issuer, extract_ownership, extract_financials,
    extract_fund_raising, extract_risks, extract_compliance,
)
from pipeline.validator.post_processor import normalize_document, validate_document
from schemas.models import DocumentResult

# 找缓存文件
CACHE_DIR = Path("data/test_output/1224871935_f9aa35f4/txt")
content_file = next(CACHE_DIR.rglob("*content_list.json"))
pdf_path = Path("data/raw_pdfs/1224871935_f9aa35f4.pdf")

logger.info(f"Loading cache: {content_file}")
raw_blocks = json.loads(content_file.read_text(encoding="utf-8"))
blocks = _normalize_blocks(raw_blocks)
total_pages = max((b.page_no for b in blocks), default=0)

doc_parsed = ParsedDocument(pdf_path=pdf_path, blocks=blocks, total_pages=total_pages)
logger.info(f"Loaded: {len(blocks)} blocks, {total_pages} pages")

# Layer 2
stitched = stitch_tables(doc_parsed)
classified = classify_blocks(stitched)
clean = filter_noise(classified)
clean_doc = ParsedDocument(pdf_path=pdf_path, blocks=clean, total_pages=total_pages)
structure = build_structure(clean_doc)
logger.info(f"TOC nodes: {len(structure.toc)}, mapped blocks: {len(structure.block_chapter_map)}")

# Layer 3
section_map = route_blocks(clean, structure)
for t, chunks in section_map.items():
    chars = sum(len(c.text) for c in chunks)
    logger.info(f"  {t}: {len(chunks)} chunks, {chars} chars")

# 若所有目标均无内容（如短公告），用全文做 issuer_profile 回退测试
total_routed = sum(len(v) for v in section_map.values())
if total_routed == 0:
    logger.warning("No section chunks routed — using full text as issuer_profile fallback")
    from pipeline.router.section_router import SectionChunk
    full_text = "\n\n".join(b.text for b in clean if b.block_type == "text")
    section_map["issuer_profile"] = [SectionChunk(
        target="issuer_profile", chapter="全文", text=full_text
    )]

# Layer 4 - LLM calls (calls DeepSeek API)
logger.info("Starting LLM extraction (6 API calls)...")
doc = DocumentResult(document_id="1224871935_f9aa35f4", document_type="上市公告书")
doc.issuer_profile       = extract_issuer(section_map["issuer_profile"])
doc.ownership_structure  = extract_ownership(section_map["ownership_structure"])
doc.financials           = extract_financials(section_map["financials"])
doc.fund_raising_projects = extract_fund_raising(section_map["fund_raising_projects"])
doc.risk_items           = extract_risks(section_map["risk_items"])
doc.compliance_items     = extract_compliance(section_map["compliance_items"])

# Layer 5
doc = normalize_document(doc)
warnings = validate_document(doc)

# Output
result = doc.model_dump()
out_path = Path("data/results/1224871935_f9aa35f4.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

logger.info(f"Done. Warnings: {warnings}")
logger.info(f"Saved → {out_path}")

# Summary
print("\n===== EXTRACTION RESULT SUMMARY =====")
ip = doc.issuer_profile
print(f"发行人: {ip.issuer_name} | {ip.establishment_date} | {ip.registered_capital.value}{ip.registered_capital.unit}")
print(f"法定代表人: {ip.legal_representative} | 交易所: {ip.exchange} | 板块: {ip.board}")
print(f"主营: {ip.main_business[:60] if ip.main_business else '(未抽取)'}")
for sh in (doc.ownership_structure.controlling_shareholder or [])[:3]:
    print(f"控股股东: {sh.name} {sh.shareholding_ratio}")
for ac in (doc.ownership_structure.actual_controller or [])[:2]:
    print(f"实控人: {ac.name} ({ac.control_type})")
for fi in (doc.financials or [])[:3]:
    print(f"财务: {fi.field_name} {fi.period} = {fi.value}{fi.unit}")
print(f"风险条目: {len(doc.risk_items)} 项")
print(f"合规条目: {len(doc.compliance_items)} 项")
for p in (doc.fund_raising_projects or [])[:2]:
    print(f"募投: {p.project_name}")
print(f"\n结果文件: {out_path.resolve()}")
