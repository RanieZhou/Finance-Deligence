"""
Layer 1: MinerU 解析封装
PDF → Block列表（保留 page_no / bbox / type / text）
"""
from __future__ import annotations
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loguru import logger


BlockType = Literal["text", "table", "image", "equation", "unknown"]


@dataclass
class Block:
    block_id: str
    page_no: int
    block_type: BlockType
    text: str                          # 文本内容或表格 HTML
    bbox: list[float] = field(default_factory=list)   # [x0, y0, x1, y1]
    raw: dict = field(default_factory=dict)            # 原始 block 数据备用


@dataclass
class ParsedDocument:
    pdf_path: Path
    blocks: list[Block]
    total_pages: int

    def blocks_by_page(self, page_no: int) -> list[Block]:
        return [b for b in self.blocks if b.page_no == page_no]

    def text_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.block_type == "text"]

    def table_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.block_type == "table"]


def parse_pdf(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    mode: str = "txt",          # txt=快速文字提取（金融PDF推荐），auto=全模型解析
) -> ParsedDocument:
    """
    调用 mineru CLI 解析 PDF，返回 ParsedDocument。
    output_dir 为 None 时使用临时目录（解析完自动清理）。
    mode: "txt" 适合文字型PDF（速度快），"auto" 适合扫描件（需GPU）。
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # 若已有缓存，直接读取
    if output_dir:
        out_dir = Path(output_dir)
        all_cl = list(out_dir.rglob("*content_list.json"))
        # prefer _content_list.json (v1) over _content_list_v2.json
        existing = [f for f in all_cl if not f.name.endswith("_v2.json")] or all_cl
        if existing:
            logger.info(f"Using cached parse: {pdf_path.name}")
            raw_blocks = json.loads(existing[0].read_text(encoding="utf-8"))
            blocks = _normalize_blocks(raw_blocks)
            total_pages = max((b.page_no for b in blocks), default=0)
            return ParsedDocument(pdf_path=pdf_path, blocks=blocks, total_pages=total_pages)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.mkdtemp(prefix="mineru_")
        out_dir = Path(tmp)

    logger.info(f"Parsing [{mode}]: {pdf_path.name}")
    result = subprocess.run(
        ["mineru", "-p", str(pdf_path), "-o", str(out_dir), "-b", "pipeline", "-m", mode],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        logger.error(f"MinerU failed:\n{result.stderr[-1000:]}")
        raise RuntimeError(f"MinerU parse failed for {pdf_path.name}")

    # 找 content_list.json
    content_files = list(out_dir.rglob("*content_list.json"))
    if not content_files:
        raise FileNotFoundError(f"content_list.json not found in {out_dir}")

    raw_blocks: list[dict] = json.loads(content_files[0].read_text(encoding="utf-8"))
    blocks = _normalize_blocks(raw_blocks)

    total_pages = max((b.page_no for b in blocks), default=0)
    logger.info(f"Done: {len(blocks)} blocks, {total_pages} pages")

    return ParsedDocument(pdf_path=pdf_path, blocks=blocks, total_pages=total_pages)


def _normalize_blocks(raw: list[dict]) -> list[Block]:
    """将 MinerU content_list 条目统一为 Block 对象"""
    blocks = []
    for i, item in enumerate(raw):
        block_type = _map_type(item.get("type", ""))
        text = _extract_text(item, block_type)
        page_no = item.get("page_idx", item.get("page_no", 0))
        # MinerU page_idx 从 0 开始，统一转为从 1 开始
        if isinstance(page_no, int):
            page_no = page_no + 1

        bbox = item.get("bbox", [])

        blocks.append(Block(
            block_id=f"b{i:05d}",
            page_no=page_no,
            block_type=block_type,
            text=text,
            bbox=bbox,
            raw=item,
        ))
    return blocks


def _map_type(raw_type: str) -> BlockType:
    mapping = {
        "text": "text",
        "table": "table",
        "table_body": "table",
        "image": "image",
        "equation": "equation",
        "interline_equation": "equation",
    }
    return mapping.get(raw_type, "text")


def _extract_text(item: dict, block_type: BlockType) -> str:
    if block_type == "table":
        # 优先取 HTML，降级取 markdown，再降级取 text
        return (
            item.get("table_body", "")
            or item.get("html", "")
            or item.get("text", "")
            or item.get("md", "")
        )
    return item.get("text", "") or item.get("md", "")
