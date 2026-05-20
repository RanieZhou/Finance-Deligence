"""
Layer 3: 章节路由
将 blocks 按内容归类到 6 个抽取目标，返回每个目标的文本片段。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pipeline.parser.mineru_parser import Block
from pipeline.structure.toc_parser import DocumentStructure

# 六类抽取目标
TARGET_ISSUER      = "issuer_profile"
TARGET_OWNERSHIP   = "ownership_structure"
TARGET_FINANCIALS  = "financials"
TARGET_FUND        = "fund_raising_projects"
TARGET_RISK        = "risk_items"
TARGET_COMPLIANCE  = "compliance_items"

# 章节标题关键词 → 抽取目标映射
_CHAPTER_RULES: list[tuple[re.Pattern, str]] = [
    # 发行人基础信息
    (re.compile(r"发行人基本情况|公司基本情况|发行人概况|发行人简介|发行人及本次发行|公司简介|主体基本情况|基本信息"), TARGET_ISSUER),
    # 股权与控制关系
    (re.compile(r"股权结构|控制关系|实际控制人|控股股东|持有.*5%以上|持有.*股份的股东|股东及实际控制人|股权关系|控股关系|主要股东"), TARGET_OWNERSHIP),
    # 财务指标
    (re.compile(r"财务会计|财务报表|财务信息|管理层分析|财务状况|主要财务数据|主要财务指标|经营成果|财务数据摘要|财务摘要|财务概要"), TARGET_FINANCIALS),
    # 募投项目
    (re.compile(r"募集资金|募投项目|资金运用|募资用途|募集资金运用计划|募集资金用途|本次募集|资金使用计划"), TARGET_FUND),
    # 风险事项
    (re.compile(r"风险因素|重大风险|风险提示|重大事项提示"), TARGET_RISK),
    # 合规事项
    (re.compile(r"处罚|诉讼|仲裁|关联交易|对外担保|承诺事项|或有事项|其他重要事项|法律事项|重要合同"), TARGET_COMPLIANCE),
]

# 每个目标最多保留的字符数（financials 章节更长，在 _trim_chunks 里按目标差异化）
MAX_CHARS_PER_TARGET = 20_000


@dataclass
class SectionChunk:
    target: str
    chapter: str
    text: str
    source_blocks: list[str] = field(default_factory=list)  # block_ids


def route_blocks(
    blocks: list[Block],
    structure: DocumentStructure,
) -> dict[str, list[SectionChunk]]:
    """
    返回 {target: [SectionChunk, ...]} 的字典。
    一个 block 可归属多个 target（如财务附注同时归属 financials 和 compliance）。
    """
    target_map: dict[str, list[SectionChunk]] = {
        TARGET_ISSUER: [],
        TARGET_OWNERSHIP: [],
        TARGET_FINANCIALS: [],
        TARGET_FUND: [],
        TARGET_RISK: [],
        TARGET_COMPLIANCE: [],
    }

    has_toc = bool(structure.toc)

    # 按章节聚合 blocks
    chapter_blocks: dict[str, list[Block]] = {}
    for block in blocks:
        if block.block_type not in ("text", "table"):
            continue
        if block.block_id not in structure.block_chapter_map:
            # Block 未被 TOC 映射（可能是 TOC 页本身或封面块）
            if has_toc:
                continue  # 有 TOC 时跳过未映射的块（避免 TOC 内容污染）
            # 无 TOC 时用全文关键词路由
            chapter = "未知章节"
        else:
            chapter = structure.block_chapter_map[block.block_id]
        chapter_blocks.setdefault(chapter, []).append(block)

    for chapter, ch_blocks in chapter_blocks.items():
        targets = _match_targets(chapter)
        if not targets:
            if not has_toc:
                # 无 TOC 时按 block 内容关键词路由（逐块匹配）
                for block in ch_blocks:
                    bt = _match_targets(block.text[:200])
                    if bt:
                        txt = block.text
                        bid = [block.block_id]
                        for t in bt:
                            target_map[t].append(
                                SectionChunk(target=t, chapter=chapter,
                                             text=txt, source_blocks=bid)
                            )
            continue
        text = _blocks_to_text(ch_blocks)
        block_ids = [b.block_id for b in ch_blocks]
        for target in targets:
            target_map[target].append(
                SectionChunk(target=target, chapter=chapter,
                             text=text, source_blocks=block_ids)
            )

    # 截断超长文本，防止 LLM 上下文溢出
    for target in target_map:
        target_map[target] = _trim_chunks(target_map[target], MAX_CHARS_PER_TARGET)

    return target_map


def _match_targets(chapter: str) -> list[str]:
    matched = []
    for pattern, target in _CHAPTER_RULES:
        if pattern.search(chapter):
            matched.append(target)
    return matched


def _blocks_to_text(blocks: list[Block]) -> str:
    parts = []
    for b in blocks:
        prefix = f"[p{b.page_no}] "
        if b.block_type == "table":
            parts.append(f"{prefix}[表格]\n{b.text}\n[/表格]")
        else:
            parts.append(f"{prefix}{b.text}")
    return "\n\n".join(parts)


def _trim_chunks(chunks: list[SectionChunk], max_chars: int) -> list[SectionChunk]:
    """若章节内容过长，按最大字符数截断（保留最重要的前几个章节）"""
    result = []
    total = 0
    for chunk in chunks:
        if total >= max_chars:
            break
        remaining = max_chars - total
        if len(chunk.text) > remaining:
            chunk = SectionChunk(
                target=chunk.target,
                chapter=chunk.chapter,
                text=chunk.text[:remaining] + "\n[内容截断]",
                source_blocks=chunk.source_blocks,
            )
        result.append(chunk)
        total += len(chunk.text)
    return result
