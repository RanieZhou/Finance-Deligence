"""
FastAPI 服务：PDF 上传 → 结构化抽取
端口: 8000
"""
from __future__ import annotations
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.run import run_pipeline
from schemas.models import DocumentResult

app = FastAPI(
    title="Finance Due-Diligence Extraction API",
    description="基于 MinerU 的企业授信尽调关键信息抽取",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR  = Path(__file__).parent.parent / "data/uploads"
RESULT_DIR  = Path(__file__).parent.parent / "data/results"
CACHE_DIR   = Path(__file__).parent.parent / "data/mineru_output"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 内存中的任务状态（生产环境换 Redis）
_job_status: dict[str, dict] = {}


@app.get("/health")
def health():
    return {"status": "ok", "service": "finance-extraction"}


@app.post("/extract", response_model=DocumentResult)
async def extract_sync(
    file: UploadFile = File(..., description="PDF 文件"),
    parse_mode: str = Form(default="txt", description="txt=快速/auto=自动"),
):
    """同步抽取：上传 PDF，等待完成后返回 DocumentResult JSON。
    适合单文件测试，生产建议用 /extract/async。"""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    doc_id = Path(file.filename).stem
    # 如已有结果，直接返回
    cached = RESULT_DIR / f"{doc_id}.json"
    if cached.exists():
        import json
        return DocumentResult.model_validate_json(cached.read_text(encoding="utf-8"))

    # 保存上传文件
    pdf_path = UPLOAD_DIR / file.filename
    with pdf_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        doc = run_pipeline(
            pdf_path,
            output_dir=RESULT_DIR,
            mineru_cache_dir=CACHE_DIR / doc_id,
            parse_mode=parse_mode,
        )
        return doc
    except Exception as e:
        logger.error(f"Extract failed for {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if pdf_path.exists():
            pdf_path.unlink()


@app.post("/extract/async", status_code=202)
async def extract_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    parse_mode: str = Form(default="txt"),
):
    """异步抽取：立即返回 job_id，后台处理。通过 /jobs/{job_id} 查询状态。"""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    job_id = str(uuid.uuid4())[:8]
    doc_id = Path(file.filename).stem
    pdf_path = UPLOAD_DIR / f"{job_id}_{file.filename}"

    with pdf_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    _job_status[job_id] = {"status": "pending", "doc_id": doc_id}
    background_tasks.add_task(_run_job, job_id, pdf_path, doc_id, parse_mode)
    return {"job_id": job_id, "doc_id": doc_id, "status": "pending"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in _job_status:
        raise HTTPException(status_code=404, detail="Job not found")
    info = _job_status[job_id]
    if info["status"] == "done":
        result_path = RESULT_DIR / f"{info['doc_id']}.json"
        if result_path.exists():
            import json
            info["result"] = json.loads(result_path.read_text(encoding="utf-8"))
    return info


@app.get("/results/{doc_id}", response_model=DocumentResult)
def get_result(doc_id: str):
    path = RESULT_DIR / f"{doc_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"结果不存在: {doc_id}")
    return DocumentResult.model_validate_json(path.read_text(encoding="utf-8"))


@app.get("/results")
def list_results(limit: int = 50):
    files = sorted(RESULT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in files[:limit]]


async def _run_job(job_id: str, pdf_path: Path, doc_id: str, parse_mode: str):
    _job_status[job_id]["status"] = "running"
    try:
        run_pipeline(
            pdf_path,
            output_dir=RESULT_DIR,
            mineru_cache_dir=CACHE_DIR / doc_id,
            parse_mode=parse_mode,
        )
        _job_status[job_id]["status"] = "done"
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        _job_status[job_id]["status"] = "failed"
        _job_status[job_id]["error"] = str(e)
    finally:
        if pdf_path.exists():
            pdf_path.unlink()
