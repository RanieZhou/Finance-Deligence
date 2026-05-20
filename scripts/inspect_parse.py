"""
查看 MinerU 解析结果的结构，帮助理解 block 格式
用法: python scripts/inspect_parse.py
"""
import sys, json
from pathlib import Path

OUTPUT_DIR = Path.home() / "Desktop/finance-due-diligence/data/test_output"

files = list(OUTPUT_DIR.rglob("*content_list.json"))
if not files:
    print("还没有解析结果，等 MinerU 跑完再运行")
    sys.exit(1)

data: list = json.loads(files[0].read_text(encoding="utf-8"))
print(f"文件: {files[0]}")
print(f"总 block 数: {len(data)}\n")

# 类型分布
types = {}
for b in data:
    t = b.get("type", "unknown")
    types[t] = types.get(t, 0) + 1
print("Block 类型分布:")
for t, cnt in sorted(types.items(), key=lambda x: -x[1]):
    print(f"  {t}: {cnt}")

# 打印前 5 个 block 结构
print(f"\n--- 前 5 个 block 字段 ---")
for i, block in enumerate(data[:5]):
    print(f"\n[{i}] keys: {list(block.keys())}")
    print(f"     type: {block.get('type')}")
    print(f"     page_idx: {block.get('page_idx', block.get('page_no', '?'))}")
    text = block.get('text', block.get('md', ''))[:100]
    print(f"     text[:100]: {repr(text)}")
    if 'bbox' in block:
        print(f"     bbox: {block['bbox']}")

# 打印第一个 table block
tables = [b for b in data if b.get("type") in ("table", "table_body")]
if tables:
    print(f"\n--- 第一个 table block ---")
    t = tables[0]
    print(f"keys: {list(t.keys())}")
    for k in ("table_body", "html", "md", "text"):
        if k in t:
            print(f"{k}[:300]: {str(t[k])[:300]}")
            break
