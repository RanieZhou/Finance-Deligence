"""
端到端流水线测试（使用 MinerU 缓存）
用法: cd ~/Desktop/finance-due-diligence && python scripts/test_pipeline.py

先运行:
  source .venv/bin/activate
  mineru -p <pdf> -o data/test_output -b pipeline -m txt
再运行本脚本
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
_parser = argparse.ArgumentParser(description="Pipeline test")
_parser.add_argument("--pdf", default=str(Path.home() / "Desktop/MinerU/附件/金融赛题/公开披露材料/finance_pdfs/1219186950_e5bbde56.pdf"))
_parser.add_argument("--cache", default=str(Path.home() / "Desktop/finance-due-diligence/data/test_output2"))
_args = _parser.parse_args()

PDF_PATH  = Path(_args.pdf)
CACHE_DIR = Path(_args.cache)

print(f"PDF: {PDF_PATH.name}")
print(f"Cache: {CACHE_DIR}")

# ─── Layer 1: 解析 ────────────────────────────────────────
from pipeline.parser.mineru_parser import parse_pdf
parsed = parse_pdf(PDF_PATH, output_dir=CACHE_DIR)
print(f"\nLayer 1: {len(parsed.blocks)} blocks, {parsed.total_pages} pages")

# ─── Layer 2: 结构恢复 ────────────────────────────────────
from pipeline.structure.table_stitcher import stitch_tables
from pipeline.structure.block_classifier import classify_blocks, filter_noise
from pipeline.structure.toc_parser import build_structure
from pipeline.parser.mineru_parser import ParsedDocument

stitched = stitch_tables(parsed)
classified = classify_blocks(stitched)
clean = filter_noise(classified)
clean_doc = ParsedDocument(pdf_path=parsed.pdf_path, blocks=clean, total_pages=parsed.total_pages)
structure = build_structure(clean_doc)

print(f"\nLayer 2:")
print(f"  Clean blocks: {len(clean)}")
print(f"  TOC nodes: {len(structure.toc)}")
if structure.toc:
    for node in structure.toc[:5]:
        print(f"    L{node.level}: {node.title[:50]} (p{node.page_no})")
print(f"  Mapped blocks: {len(structure.block_chapter_map)}")

# ─── Layer 3: 路由 ────────────────────────────────────────
from pipeline.router.section_router import route_blocks

section_map = route_blocks(clean, structure)
print(f"\nLayer 3: Section routing")
has_content = False
for target, chunks in section_map.items():
    total_chars = sum(len(c.text) for c in chunks)
    print(f"  {target}: {len(chunks)} chunks, {total_chars} chars")
    if total_chars > 0:
        has_content = True

if not has_content:
    print("\n[WARN] 所有目标均无内容，可能需要更多页面或 TOC 解析改进")
    print("       当前解析为前 25 页，需完整文档才能覆盖所有章节")
    sys.exit(0)

# ─── Layer 4+5: LLM 抽取（需要 DEEPSEEK_API_KEY）────────────
from dotenv import load_dotenv
import os
load_dotenv()

if not os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY") == "your_key_here":
    print("\n[SKIP] Layer 4+5: DEEPSEEK_API_KEY 未配置，跳过 LLM 抽取")
    print("       在 .env 中填入 DEEPSEEK_API_KEY 后重新运行")
    sys.exit(0)

from pipeline.run import run_pipeline
print("\nLayer 4+5: LLM 抽取 + 后处理...")
doc = run_pipeline(PDF_PATH, output_dir=Path("data/results"), mineru_cache_dir=CACHE_DIR)
print(f"\n[OK] 抽取完成!")
print(f"  发行人: {doc.issuer_profile.issuer_name}")
print(f"  财务指标: {len(doc.financials)} 条")
print(f"  风险事项: {len(doc.risk_items)} 条")
print(f"  证据索引: {len(doc.evidence_index)} 条")

result_path = Path("data/results") / f"{PDF_PATH.stem}.json"
if result_path.exists():
    print(f"\n结果已保存: {result_path}")
