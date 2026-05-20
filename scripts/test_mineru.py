"""测试 MinerU 能否解析一份金融PDF"""
import subprocess, sys, pathlib, json, time

PDF_PATH = pathlib.Path.home() / "Desktop/MinerU/附件/金融赛题/公开披露材料/finance_pdfs/000064_20190611_31LJ_867634ab.pdf"
OUTPUT_DIR = pathlib.Path.home() / "Desktop/finance-due-diligence/data/test_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"测试PDF: {PDF_PATH.name}")
print(f"输出目录: {OUTPUT_DIR}")
print("开始解析（首次较慢，约1-3分钟）...\n")

start = time.time()
result = subprocess.run(
    ["mineru", "-p", str(PDF_PATH), "-o", str(OUTPUT_DIR), "-b", "pipeline", "-m", "txt"],
    capture_output=True, text=True
)
elapsed = time.time() - start

print(f"耗时: {elapsed:.1f}s")
print(f"返回码: {result.returncode}")

if result.returncode == 0:
    # 找输出文件
    outputs = list(OUTPUT_DIR.rglob("*content_list.json"))
    mds = list(OUTPUT_DIR.rglob("*.md"))
    print(f"\n[OK] 解析成功!")
    print(f"  JSON文件: {len(outputs)} 个")
    print(f"  MD文件:   {len(mds)} 个")

    if outputs:
        data = json.loads(outputs[0].read_text())
        print(f"  Block数量: {len(data)}")
        types = {}
        for block in data:
            t = block.get("type", "unknown")
            types[t] = types.get(t, 0) + 1
        print(f"  Block类型分布: {types}")
else:
    print(f"\n[FAIL] 解析失败")
    print("STDOUT:", result.stdout[-500:])
    print("STDERR:", result.stderr[-500:])
