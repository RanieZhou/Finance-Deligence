"""
竞赛结果汇总脚本
读取 data/results/*.json，输出统计报告，并打包为 submission.zip。
用法: cd ~/Desktop/finance-due-diligence && python scripts/collect_results.py
"""
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

RESULT_DIR = Path("data/results")
PDF_DIR    = Path("data/raw_pdfs")


def main():
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    results = sorted(RESULT_DIR.glob("*.json"))

    print(f"PDF 总数: {len(pdfs)}")
    print(f"结果文件数: {len(results)}")

    # 找出缺失的
    pdf_ids = {p.stem for p in pdfs}
    result_ids = {r.stem for r in results}
    missing = pdf_ids - result_ids
    if missing:
        print(f"\n缺失结果 ({len(missing)} 份):")
        for m in sorted(missing)[:20]:
            print(f"  {m}")
        if len(missing) > 20:
            print(f"  ...共 {len(missing)} 份")

    # 统计字段覆盖率
    stats = {
        "issuer_name_filled": 0,
        "has_financials": 0,
        "has_risks": 0,
        "has_ownership": 0,
        "has_fund_raising": 0,
        "has_compliance": 0,
        "has_evidence": 0,
    }
    for f in results:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("issuer_profile", {}).get("issuer_name"):
            stats["issuer_name_filled"] += 1
        if d.get("financials"):
            stats["has_financials"] += 1
        if d.get("risk_items"):
            stats["has_risks"] += 1
        if d.get("ownership_structure", {}).get("top_shareholders"):
            stats["has_ownership"] += 1
        if d.get("fund_raising_projects"):
            stats["has_fund_raising"] += 1
        if d.get("compliance_items"):
            stats["has_compliance"] += 1
        if d.get("evidence_index"):
            stats["has_evidence"] += 1

    n = len(results)
    if n > 0:
        print(f"\n字段覆盖率 (共 {n} 份):")
        for k, v in stats.items():
            print(f"  {k}: {v}/{n} ({100*v//n}%)")

    # 打包 submission.zip
    zip_path = Path("submission.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in results:
            zf.write(f, f"results/{f.name}")
    print(f"\n已打包: {zip_path} ({zip_path.stat().st_size // 1024} KB, {len(results)} 份结果)")


if __name__ == "__main__":
    main()
