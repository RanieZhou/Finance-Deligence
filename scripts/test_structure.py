"""
结构恢复单元测试（不依赖 MinerU，使用 mock 数据）
验证 TOC 解析 / block→chapter 映射 / 章节路由
用法: cd ~/Desktop/finance-due-diligence && python scripts/test_structure.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.parser.mineru_parser import Block, ParsedDocument
from pipeline.structure.toc_parser import build_structure
from pipeline.structure.block_classifier import classify_blocks, filter_noise
from pipeline.router.section_router import route_blocks

# ── 构造 mock 文档 ────────────────────────────────────────
def make_block(i, page, text, btype="text", y0=200, y1=220):
    return Block(
        block_id=f"b{i:05d}",
        page_no=page,
        block_type=btype,
        text=text,
        bbox=[50, y0, 800, y1],
        raw={"type": "text", "page_idx": page - 1}
    )


# Mock 典型招股说明书前 25 页
blocks = []
i = 0

# Page 1-2: Cover pages (no useful content)
blocks.append(make_block(i, 1, "某某股份有限公司 招股说明书", btype="text")); i+=1

# Page 3-5: TOC pages (dot-line patterns)
toc_lines = [
    "第一节 发行人基本情况......................1",
    "一、基本信息...............................2",
    "二、主营业务...............................3",
    "第二节 风险因素...........................10",
    "一、市场风险...............................11",
    "二、财务风险...............................12",
    "第三节 募集资金运用.......................20",
    "一、募投项目概览...........................21",
    "第四节 财务会计信息.......................30",
    "一、合并资产负债表.........................31",
    "二、合并利润表.............................35",
    "第五节 股权结构与控制关系.................45",
    "一、控股股东情况...........................46",
]
blocks.append(make_block(i, 3, "\n".join(toc_lines[:5]))); i+=1
blocks.append(make_block(i, 4, "\n".join(toc_lines[5:10]))); i+=1
blocks.append(make_block(i, 5, "\n".join(toc_lines[10:]))); i+=1

# Page 1-10 content (Chapter 1: 发行人基本情况)
blocks.append(make_block(i, 1, "第一节 发行人基本情况", y0=80, y1=100)); i+=1
blocks.append(make_block(i, 1, "公司全称：某某科技股份有限公司，成立于2010年1月1日，注册资本1亿元。")); i+=1
blocks.append(make_block(i, 2, "法定代表人：张三，注册地址：北京市朝阳区某某路1号。")); i+=1
blocks.append(make_block(i, 3, "主营业务：专注于软件开发和技术服务，在国内拥有核心专利技术200余项。")); i+=1

# Page 10-15: Chapter 2 (风险因素)
blocks.append(make_block(i, 10, "第二节 风险因素")); i+=1
blocks.append(make_block(i, 10, "一、市场风险：公司所在行业竞争激烈，存在客户集中度较高的风险。")); i+=1
blocks.append(make_block(i, 11, "二、财务风险：公司应收账款回收期较长，存在坏账风险。")); i+=1
blocks.append(make_block(i, 12, "三、技术风险：核心技术可能面临迭代更新，存在技术路线选择风险。")); i+=1

# Page 20-25: Chapter 3 (募集资金)
blocks.append(make_block(i, 20, "第三节 募集资金运用")); i+=1
blocks.append(make_block(i, 21, "一、募投项目概览：公司拟募集资金5亿元用于以下项目：")); i+=1
blocks.append(make_block(i, 22, "项目一：研发中心建设，总投资2.5亿元，拟使用募集资金2亿元，建设周期2年。")); i+=1
blocks.append(make_block(i, 23, "项目二：市场拓展，总投资1.5亿元，拟使用募集资金1.5亿元。")); i+=1

# Page 30-35: Chapter 4 (财务信息)
blocks.append(make_block(i, 30, "第四节 财务会计信息与管理层分析")); i+=1
blocks.append(make_block(i, 31, "合并资产负债表：总资产50亿元，总负债20亿元，净资产30亿元（2022年12月31日）。")); i+=1
blocks.append(make_block(i, 32, "合并利润表：营业收入30亿元，净利润5亿元（2022年度）。")); i+=1
blocks.append(make_block(i, 33, "研发费用：合并利润表口径2亿元，占营业收入6.7%。")); i+=1

# Page 45-48: Chapter 5 (股权)
blocks.append(make_block(i, 45, "第五节 股权结构与控制关系")); i+=1
blocks.append(make_block(i, 46, "控股股东：张三持有公司60%股权（直接持有），系本公司实际控制人。")); i+=1
blocks.append(make_block(i, 47, "前十大股东：张三60%，李四15%，王五5%...")); i+=1

total_blocks = i
total_pages = 50

doc = ParsedDocument(
    pdf_path=Path("/mock/test.pdf"),
    blocks=blocks,
    total_pages=total_pages,
)

print(f"Mock document: {len(blocks)} blocks, {total_pages} pages")

# ── Layer 2: 结构恢复 ────────────────────────────────────
classified = classify_blocks(blocks)
clean_blocks = filter_noise(classified)
clean_doc = ParsedDocument(pdf_path=doc.pdf_path, blocks=clean_blocks, total_pages=total_pages)
structure = build_structure(clean_doc)

print(f"\nLayer 2:")
print(f"  Clean blocks: {len(clean_blocks)}")
print(f"  TOC nodes: {len(structure.toc)}")
for node in structure.toc[:8]:
    prefix = "  " * (node.level - 1)
    print(f"    {prefix}L{node.level}: {node.title} (p{node.page_no})")
print(f"  Mapped blocks: {len(structure.block_chapter_map)}")

# Show some mappings
if structure.block_chapter_map:
    print(f"\n  Block→Chapter samples:")
    for bid, chapter in list(structure.block_chapter_map.items())[:5]:
        block = next(b for b in clean_blocks if b.block_id == bid)
        print(f"    [{bid}] p{block.page_no}: {chapter[:50]} | {block.text[:50]}")

# ── Layer 3: 路由 ────────────────────────────────────────
section_map = route_blocks(clean_blocks, structure)

print(f"\nLayer 3: Section routing")
all_have_content = True
for target, chunks in section_map.items():
    total_chars = sum(len(c.text) for c in chunks)
    if total_chars > 0:
        sample = chunks[0].text[:60].replace("\n", " ")
        print(f"  ✓ {target}: {len(chunks)} chunks, {total_chars} chars | {sample}...")
    else:
        print(f"  ✗ {target}: 0 chunks")
        all_have_content = False

print()
if all_have_content:
    print("[PASS] 所有目标均有内容，结构恢复与路由逻辑正常！")
else:
    print("[WARN] 部分目标无内容（可检查 TOC 关键词匹配）")
