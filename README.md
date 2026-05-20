# 金融尽调信息抽取系统

**2026 MinerU 数据智能挑战赛 · 赛道三：场景攻坚·行业应用转化赛道**  
赛题：基于 MinerU 的企业授信尽调的关键信息抽取

---

## 快速开始

### 1. 环境准备

```bash
# 已完成：创建虚拟环境并安装依赖
cd ~/Desktop/finance-due-diligence
source .venv/bin/activate

# 配置 DeepSeek API Key（必须）
vim .env   # 填入 DEEPSEEK_API_KEY=sk-xxx
```

### 2. 测试单份 PDF

```bash
# 使用已缓存的 MinerU 解析结果
python scripts/test_pipeline.py
```

### 3. 启动 Demo 服务

```bash
./start_demo.sh
# 访问 http://127.0.0.1:8000/docs  → API 文档
# 打开 frontend/index.html          → 可视化演示
```

### 4. 批量处理 300 份 PDF

```bash
# Phase 1: MinerU 批量解析（所有 PDF 模型加载一次，推荐 GPU 服务器运行）
python batch/batch_parse.py

# Phase 2: LLM 信息抽取（并发度 4，需要 DEEPSEEK_API_KEY）
python batch/run_batch.py
```

---

## 项目结构

```
finance-due-diligence/
├── api/              FastAPI 服务
│   └── main.py      POST /extract, GET /results/{doc_id}
├── batch/
│   ├── batch_parse.py   Phase 1: MinerU 批量解析
│   └── run_batch.py     Phase 2: LLM 并发抽取
├── data/
│   ├── raw_pdfs/    原始 PDF（软链接到竞赛数据）
│   ├── mineru_output/  MinerU 解析缓存
│   └── results/     抽取结果 JSON
├── docs/
│   └── technical_solution.md  技术方案说明书
├── frontend/
│   └── index.html   可视化演示前端
├── pipeline/
│   ├── parser/      Layer 1: MinerU 封装
│   ├── structure/   Layer 2: TOC/表格/过滤
│   ├── router/      Layer 3: 章节路由
│   ├── extractor/   Layer 4: LLM 抽取
│   ├── validator/   Layer 5: 后处理
│   └── run.py       端到端入口
├── schemas/
│   └── models.py    Pydantic Schema（8 个数据模型）
├── scripts/
│   ├── verify_env.py    环境检查
│   ├── test_mineru.py   MinerU 单元测试
│   ├── inspect_parse.py 查看 MinerU 输出结构
│   └── test_pipeline.py 端到端流水线测试
├── .env             环境变量（需填 DEEPSEEK_API_KEY）
├── requirements.txt
└── start_demo.sh    一键启动演示
```

---

## 输出格式

每份 PDF 输出一个 JSON 文件，结构如下：

```json
{
  "document_id": "000064_20190611_31LJ_867634ab",
  "document_type": "招股说明书",
  "issuer_profile": { ... },
  "ownership_structure": { "controlling_shareholder": [...], "top_shareholders": [...] },
  "financials": [ { "field_name": "营业收入", "field_scope": "合并利润表", "period": "2022-12-31", "value": 123456.0, ... } ],
  "fund_raising_projects": [...],
  "risk_items": [...],
  "compliance_items": [...],
  "evidence_index": [ { "evidence_id": "ev_0001", "page_no": 168, ... } ]
}
```

详见 `docs/technical_solution.md`。

---

## 性能参考

| 环境 | MinerU 解析速度 | 300份PDF总时间 |
|------|----------------|----------------|
| MacBook Air M4 | ~5s/页（CPU pipeline） | ~10-20小时（不推荐批量） |
| GPU服务器（A100/RTX3090） | ~0.3s/页 | ~3-6小时 |

**推荐策略**：
- 本地 M4：开发调试，每次测试 1-2 份 PDF 前 20 页
- GPU 服务器：生产批量，一次性解析所有 300 份 PDF

---

## 技术栈

- **PDF 解析**：MinerU 3.1.14（`-b pipeline` 纯算法模式）
- **LLM**：DeepSeek Chat API（OpenAI 兼容）
- **框架**：FastAPI + Pydantic v2
- **运行环境**：Python 3.11，macOS M4（本地开发）/ GPU 服务器（批量生产）
