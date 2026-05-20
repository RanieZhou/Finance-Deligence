"""
Phase 2: 批量 LLM 抽取
前提：data/mineru_output/ 已由 batch_parse.py 填满。
逐个 PDF 跑 Layer 2-5（结构恢复 + 路由 + LLM + 后处理），支持并发抽取。
"""
from __future__ import annotations
import sys
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.run import run_pipeline

PDF_DIR    = Path(__file__).parent.parent / "data/raw_pdfs"
CACHE_DIR  = Path(__file__).parent.parent / "data/mineru_output"
RESULT_DIR = Path(__file__).parent.parent / "data/results"
LOG_FILE   = Path(__file__).parent.parent / "data/batch.log"

# LLM 并发数（DeepSeek API 限速宽松，3-5 并发安全）
LLM_WORKERS = 4


def process_one(pdf_path: Path) -> dict:
    doc_id = pdf_path.stem
    out_file = RESULT_DIR / f"{doc_id}.json"

    if out_file.exists():
        logger.info(f"[SKIP] {doc_id}")
        return {"doc_id": doc_id, "status": "skipped"}

    cache = CACHE_DIR / doc_id
    if not list(cache.rglob("*content_list.json")):
        logger.warning(f"[NO-CACHE] {doc_id}: MinerU 缓存不存在，跳过（先运行 batch_parse.py）")
        return {"doc_id": doc_id, "status": "no_cache"}

    start = time.time()
    try:
        run_pipeline(pdf_path, output_dir=RESULT_DIR, mineru_cache_dir=cache)
        elapsed = time.time() - start
        logger.success(f"[OK] {doc_id} ({elapsed:.0f}s)")
        return {"doc_id": doc_id, "status": "ok", "elapsed": elapsed}
    except Exception as e:
        logger.error(f"[FAIL] {doc_id}: {e}")
        return {"doc_id": doc_id, "status": "fail", "error": str(e)}


def main():
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(LOG_FILE, rotation="50 MB", level="INFO")

    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        logger.error(f"PDF 目录为空: {PDF_DIR}")
        return

    logger.info(f"共 {len(pdfs)} 份 PDF，并发度={LLM_WORKERS}")
    stats: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=LLM_WORKERS) as pool:
        futures = {pool.submit(process_one, pdf): pdf for pdf in pdfs}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            status = result["status"]
            stats[status] = stats.get(status, 0) + 1
            if i % 10 == 0:
                logger.info(f"进度: {i}/{len(pdfs)} | {stats}")

    logger.info(f"批量完成: {stats}")


if __name__ == "__main__":
    main()
