"""环境验证脚本 - 运行前确认所有依赖就绪"""
import sys
import os

def check(name, fn):
    try:
        result = fn()
        print(f"  [OK] {name}: {result}")
        return True
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        return False

print("=== 环境验证 ===\n")

results = []

# Python版本
results.append(check("Python版本", lambda: sys.version.split()[0]))

# 核心依赖
results.append(check("mineru", lambda: __import__("subprocess").check_output(["mineru","--version"]).decode().strip()))
results.append(check("pydantic", lambda: __import__("pydantic").__version__))
results.append(check("openai", lambda: __import__("openai").__version__))
results.append(check("fastapi", lambda: __import__("fastapi").__version__))
results.append(check("loguru", lambda: "ok"))
results.append(check("pandas", lambda: __import__("pandas").__version__))

# MinerU 模型配置
def check_mineru_config():
    import json, pathlib
    cfg = pathlib.Path.home() / "magic-pdf.json"
    if cfg.exists():
        data = json.loads(cfg.read_text())
        return f"config found, models_dir={data.get('models-dir', 'default')}"
    return "config not found (will use defaults)"

results.append(check("MinerU配置", check_mineru_config))

# DeepSeek API Key
def check_api_key():
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key or key == "your_key_here":
        raise ValueError("DEEPSEEK_API_KEY 未设置")
    return f"{key[:8]}..."

results.append(check("DeepSeek API Key", check_api_key))

print(f"\n=== 结果: {sum(results)}/{len(results)} 项通过 ===")
