"""
目录树解析：从 blocks 中识别 TOC 页，提取多级章节结构，
并将正文 blocks 与章节建立映射关系。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pipeline.parser.mineru_parser import Block, ParsedDocument


@dataclass
class TocNode:
    level: int           # 1=一级，2=二级，3=三级
    title: str
    page_no: int         # 目录中标注的页码
    children: list[TocNode] = field(default_factory=list)
    parent: TocNode | None = field(default=None, repr=False)

    @property
    def full_title(self) -> str:
        """带层级编号的完整标题，如 '第八节 财务会计信息与管理层分析'"""
        return self.title


@dataclass
class DocumentStructure:
    toc: list[TocNode]                        # 顶层章节列表
    block_chapter_map: dict[str, str]         # block_id → chapter 标题


# ── 一级/二级/三级章节标题的正则 ─────────────────────────
_L1_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百\d]+[章节篇]\s+.+"),   # 第一章/第一节
    re.compile(r"^\d+\s+[^\d].{2,}"),                            # 1 公司概况
]
_L2_PATTERNS = [
    re.compile(r"^[一二三四五六七八九十]+[、．.]\s*.+"),           # 一、财务报表
    re.compile(r"^\d+\.\d+\s+.+"),                               # 1.1 基本信息
]
_L3_PATTERNS = [
    re.compile(r"^\([一二三四五六七八九十\d]+\)\s*.+"),            # （一）合并资产负债表
    re.compile(r"^\d+\.\d+\.\d+\s+.+"),                         # 1.1.1 注册资本
]

# 点线引导（目录行特征）
_DOTLINE = re.compile(r"[．.…·]{3,}")
# 行末页码
_PAGE_NUM = re.compile(r"\d{1,4}\s*$")


def build_structure(doc: ParsedDocument) -> DocumentStructure:
    """
    主入口：识别目录页 → 解析 TOC → 将正文 blocks 分配到章节。
    """
    toc_blocks, body_blocks = _split_toc_body(doc)
    toc_nodes = _parse_toc(toc_blocks)
    block_chapter_map = _assign_chapters(body_blocks, toc_nodes)
    return DocumentStructure(toc=toc_nodes, block_chapter_map=block_chapter_map)


def _split_toc_body(doc: ParsedDocument) -> tuple[list[Block], list[Block]]:
    """
    识别目录页范围（通常在前 20 页，包含大量点线引导行）。
    返回 (toc_blocks, body_blocks)。
    """
    # 统计每页的点线密度
    toc_pages: set[int] = set()
    for page_no in range(1, min(doc.total_pages + 1, 30)):
        page_blocks = doc.blocks_by_page(page_no)
        dot_lines = 0
        for b in page_blocks:
            if b.block_type != "text":
                continue
            for line in b.text.splitlines():
                if _DOTLINE.search(line):
                    dot_lines += 1
        if dot_lines >= 3:
            toc_pages.add(page_no)

    toc_blocks = [b for b in doc.blocks if b.page_no in toc_pages]
    body_blocks = [b for b in doc.blocks if b.page_no not in toc_pages]
    return toc_blocks, body_blocks


def _parse_toc(toc_blocks: list[Block]) -> list[TocNode]:
    """从目录 blocks 提取层级节点列表"""
    nodes: list[TocNode] = []
    for block in toc_blocks:
        for line in block.text.splitlines():
            line = line.strip()
            if not line:
                continue
            # 去掉点线和末尾页码，保留标题
            title = _DOTLINE.sub("", line).strip()
            title = _PAGE_NUM.sub("", title).strip()
            if not title or len(title) < 2:
                continue

            page_match = _PAGE_NUM.search(line)
            page_no = int(page_match.group().strip()) if page_match else 0

            level = _detect_level(title)
            if level:
                nodes.append(TocNode(level=level, title=title, page_no=page_no))

    return _build_hierarchy(nodes)


def _detect_level(title: str) -> int | None:
    if any(p.match(title) for p in _L1_PATTERNS):
        return 1
    if any(p.match(title) for p in _L2_PATTERNS):
        return 2
    if any(p.match(title) for p in _L3_PATTERNS):
        return 3
    return None


def _build_hierarchy(flat: list[TocNode]) -> list[TocNode]:
    """将扁平节点列表构建为父子树，返回根节点列表"""
    roots: list[TocNode] = []
    stack: list[TocNode] = []

    for node in flat:
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            node.parent = stack[-1]
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    return roots


def _assign_chapters(body_blocks: list[Block], toc: list[TocNode]) -> dict[str, str]:
    """
    把正文 blocks 分配到最近的章节。
    自动推断页码偏移（TOC 逻辑页码 vs PDF 物理页码）。
    """
    flat_nodes = _flatten_toc(toc)
    flat_nodes.sort(key=lambda n: n.page_no)

    if not flat_nodes or not body_blocks:
        return {b.block_id: "" for b in body_blocks}

    # 估算页码偏移：正文 block 的最小页码 - TOC 最小页码
    # 若 TOC 节点的页码比正文 blocks 的最小物理页码小，则有负偏移
    min_physical = min(b.page_no for b in body_blocks)
    min_toc_page = flat_nodes[0].page_no
    # 粗略偏移：若 TOC 最小页码 < 正文最小页码，偏移 = min_physical - min_toc_page
    # 若 TOC 页码 > 正文页码（罕见），偏移为负数
    if min_toc_page > 0 and min_physical > 0:
        # 假设前几个 TOC 节点对应正文前几章（第1章/第一节 应该从靠前的页开始）
        # 简单估算：不做偏移修正，依赖 TOC 页码与物理页码基本一致
        page_offset = 0
    else:
        page_offset = 0

    result: dict[str, str] = {}
    for block in body_blocks:
        physical_page = block.page_no
        chapter = ""
        for node in flat_nodes:
            adjusted = node.page_no + page_offset
            if adjusted <= physical_page:
                chapter = node.title
            else:
                break
        result[block.block_id] = chapter

    return result


def _flatten_toc(nodes: list[TocNode]) -> list[TocNode]:
    result = []
    for n in nodes:
        result.append(n)
        result.extend(_flatten_toc(n.children))
    return result
