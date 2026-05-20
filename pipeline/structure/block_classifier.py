"""
Block 分类器：区分正文 / 脚注 / 页眉 / 页脚，打标签。
同时识别章节标题 block，用于辅助 TOC 映射。
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pipeline.parser.mineru_parser import Block

# 页面高度归一化后的区域阈值（0~1）
HEADER_ZONE = 0.15   # 顶部 15% 视为页眉（MinerU 实测 header block y1 ≈ 12-13%）
FOOTER_ZONE = 0.92   # 底部 8% 视为页脚

# 脚注模式：以"注1"/"注："/"①"等开头
_FOOTNOTE_PREFIX = re.compile(
    r"^[\s\n]*[注注①②③④⑤⑥⑦⑧⑨⑩\*\*][\d\s：:、]"
    r"|^[\s\n]*(注[明释]?|备注)\s*[：:：]"
    r"|^[\s\n]*\d+\s+[注注]"
)

# 页码模式（单独一行，纯数字或带格式）
_PAGE_MARK = re.compile(r"^\s*-?\s*\d+\s*-?\s*$|^\s*第\s*\d+\s*页\s*$")


@dataclass
class ClassifiedBlock:
    block: Block
    label: str   # "body" | "footnote" | "header" | "footer" | "page_mark"


def classify_blocks(blocks: list[Block], page_height: float = 841.0) -> list[ClassifiedBlock]:
    """
    为每个 block 打上内容分类标签。
    page_height: PDF 默认 A4 高度 841pt，用于归一化 bbox。
    """
    result = []
    for block in blocks:
        label = _classify(block, page_height)
        result.append(ClassifiedBlock(block=block, label=label))
    return result


def _classify(block: Block, page_height: float) -> str:
    text = block.text.strip()

    # MinerU 原生 header 标签 → 页眉
    if block.raw.get("type") == "header":
        return "header"

    # 页码标记
    if _PAGE_MARK.match(text):
        return "page_mark"

    # bbox 位置判断（页眉/页脚）
    if block.bbox and len(block.bbox) >= 4:
        y0, y1 = block.bbox[1], block.bbox[3]
        y0_norm = y0 / page_height
        y1_norm = y1 / page_height
        if y1_norm <= HEADER_ZONE:
            return "header"
        if y0_norm >= FOOTER_ZONE:
            return "footer"

    # 脚注
    if _FOOTNOTE_PREFIX.match(text):
        return "footnote"

    return "body"


def filter_noise(classified: list[ClassifiedBlock]) -> list[Block]:
    """过滤掉页眉/页脚/页码，保留 body 和 footnote"""
    return [
        cb.block for cb in classified
        if cb.label in ("body", "footnote")
    ]
