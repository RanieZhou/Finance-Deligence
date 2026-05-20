#!/bin/bash
# 启动 Demo：API 服务 + 前端页面
set -e

cd "$(dirname "$0")"

# 激活虚拟环境
source .venv/bin/activate

# 检查 API Key
if ! grep -q "DEEPSEEK_API_KEY=sk-" .env 2>/dev/null; then
  echo "[WARN] .env 中 DEEPSEEK_API_KEY 未配置，LLM 抽取将失败"
  echo "       请编辑 .env 文件并填入正确的 key"
fi

echo "启动 FastAPI 服务（后台运行）..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!
echo "API PID: $API_PID"

echo ""
echo "等待 API 就绪..."
until curl -sf http://127.0.0.1:8000/health >/dev/null; do sleep 1; done
echo "[OK] API 已就绪: http://127.0.0.1:8000"
echo "[OK] API 文档:   http://127.0.0.1:8000/docs"

echo ""
echo "打开前端页面..."
open frontend/index.html 2>/dev/null || echo "请手动打开: frontend/index.html"

echo ""
echo "按 Ctrl+C 停止服务"
wait $API_PID
