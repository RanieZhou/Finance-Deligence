"""
Phase 1: 批量 MinerU 解析（所有 PDF 一次性解析，模型只加载一次）
输出到 data/mineru_output/<doc_id>/txt/*content_list.json

在 GPU 服务器上运行效果最佳；本地 M4 也可用，但每份 PDF 约 30s（首次模型初始化约 5 分钟）。
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PDF_DIR   = Path(__file__).parent.parent / "data/raw_pdfs"
CACHE_DIR = Path(__file__).parent.parent / "data/mineru_output"


def run_batch_parse(
    pdf_dir: Path = PDF_DIR,
    output_dir: Path = CACHE_DIR,
    mode: str = "txt",
    skip_existing: bool = True,
):
    """
    调用 mineru CLI 对整个目录批量解析。
    模型只初始化一次，大幅提升吞吐。
    """
    pdf_dir = Path(pdf_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if skip_existing:
        # 找出还没有解析结果的 PDF
        pdfs = sorted(pdf_dir.glob("*.pdf"))
        pending = []
        for pdf in pdfs:
            doc_id = pdf.stem
            existing = list((output_dir / doc_id).rglob("*content_list.json"))
            if not existing:
                pending.append(pdf)
        print(f"共 {len(pdfs)} 份 PDF，{len(pdfs)-len(pending)} 份已有缓存，{len(pending)} 份待解析")
        if not pending:
            print("所有 PDF 已解析，跳过")
            return

        # 创建临时目录存放待解析 PDF 的软链接
        import tempfile, os
        tmpdir = Path(tempfile.mkdtemp(prefix="mineru_batch_"))
        for pdf in pending:
            os.symlink(pdf.resolve(), tmpdir / pdf.name)
        parse_target = tmpdir
    else:
        parse_target = pdf_dir

    print(f"开始 MinerU 批量解析: {parse_target} → {output_dir}")
    print("（首次运行需初始化模型，约 5 分钟）")

    cmd = [
        "mineru",
        "-p", str(parse_target),
        "-o", str(output_dir),
        "-b", "pipeline",
        "-m", mode,
    ]
    print(f"命令: {' '.join(cmd)}")

    result = subprocess.run(cmd, text=True)

    if skip_existing:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    if result.returncode != 0:
        print(f"[FAIL] MinerU 批量解析失败，返回码: {result.returncode}", file=sys.stderr)
        sys.exit(1)
    else:
        # 统计输出
        done = list(output_dir.rglob("*content_list.json"))
        print(f"[OK] 解析完成，共 {len(done)} 份文档有输出")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MinerU 批量解析")
    parser.add_argument("--pdf-dir", default=str(PDF_DIR))
    parser.add_argument("--output-dir", default=str(CACHE_DIR))
    parser.add_argument("--mode", default="txt", choices=["txt", "ocr", "auto"])
    parser.add_argument("--no-skip", action="store_true", help="不跳过已有结果")
    args = parser.parse_args()

    run_batch_parse(
        pdf_dir=Path(args.pdf_dir),
        output_dir=Path(args.output_dir),
        mode=args.mode,
        skip_existing=not args.no_skip,
    )
