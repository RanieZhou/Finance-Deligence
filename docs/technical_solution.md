# 技术方案说明书

## 基于 MinerU 的企业授信尽调关键信息抽取

---

## 一、方案概述

本方案针对金融行业企业授信尽调场景，基于 MinerU 解析引擎，构建了一套端到端的 PDF 文档结构化信息抽取流水线。输入为招股说明书、可转债募集说明书、上市公告书等金融类 PDF，输出为标准化 JSON 格式的结构化信息，覆盖发行人基本情况、股权结构、财务指标、募投项目、风险事项、合规事项六大维度。

---

## 二、技术架构

### 2.1 整体流水线（5 层架构）

```
PDF 文件
  │
  ▼ Layer 1: MinerU 解析
  │  • 调用 MinerU pipeline backend 提取文字块/表格/图片
  │  • 输出：Block 对象列表（block_id, page_no, bbox, text, type）
  │
  ▼ Layer 2: 结构恢复
  │  • 跨页表格拼接（Jaccard header 相似度≥0.6）
  │  • 页眉/页脚/页码过滤
  │  • TOC 目录解析 → block→chapter 映射
  │
  ▼ Layer 3: 章节路由
  │  • 基于章节标题关键词路由到 6 个抽取目标
  │  • 无 TOC 时降级为 block 内容关键词路由
  │  • 超长文本截断（12,000 字/目标）
  │
  ▼ Layer 4: LLM 抽取
  │  • DeepSeek API（OpenAI 兼容）
  │  • 6 套专业 Prompt，强制 JSON 输出
  │  • 字段口径消歧（field_scope）、证据溯源（source_evidence_id）
  │
  ▼ Layer 5: 后处理
     • 日期格式归一化（中文日期 → YYYY-MM-DD）
     • 业务规则校验（持股比例、募资一致性、指标去重）
     • 证据索引构建（页码→页面引用）
     │
     ▼ DocumentResult JSON
```

### 2.2 MinerU 集成细节

| 参数 | 取值 | 说明 |
|------|------|------|
| backend | `pipeline` | 纯传统算法，不依赖 VLM；M4 MacBook 约 10-20s/页 |
| method | `txt` | 金融 PDF 均为数字文字，无需 OCR |
| 输出 | `*content_list.json` | Block 列表，含 type/text/bbox/page_idx |

**关键发现**：MinerU 默认使用 `hybrid-auto-engine`（VLM+Pipeline 混合），在 Apple Silicon 上会自动调用 mlx-engine 加载 Qwen2VL，每页约 11 秒。显式指定 `-b pipeline` 后切换为纯 pipeline 模式，显著提速。

### 2.3 批量处理策略

```
Phase 1（batch_parse.py）：
  mineru -p <全部PDF目录> -b pipeline -m txt
  → 300 份 PDF 一次性解析，模型只加载一次（约5分钟初始化）
  → 每份 PDF 约 10-30s（依页数），全部约 1-3 小时

Phase 2（run_batch.py）：
  并发度 = 4，调用 DeepSeek API 抽取
  → 每份约 20-60s（依 LLM 响应），全部约 0.5-2 小时
```

---

## 三、数据结构设计

### 3.1 核心 Schema（`schemas/models.py`）

```python
class DocumentResult(BaseModel):
    document_id: str                    # 文件名（不含扩展名）
    document_type: str                  # 招股说明书/可转债/上市公告书
    issuer_profile: IssuerProfile       # 发行人基本信息
    ownership_structure: OwnershipStructure  # 股权控制关系
    financials: list[FinancialItem]     # 关键财务指标
    fund_raising_projects: list[FundRaisingProject]  # 募投项目
    risk_items: list[RiskItem]          # 重大风险事项
    compliance_items: list[ComplianceItem]  # 合规事项
    evidence_index: list[EvidenceItem]  # 证据溯源索引
```

### 3.2 口径消歧设计

同一指标名（如"研发费用"）在不同章节下含义不同，通过 `field_scope` 字段消歧：

| field_name | field_scope | period | value |
|------------|------------|--------|-------|
| 研发费用 | 合并利润表 | 2022 | 12345.6 |
| 研发费用 | 募投项目预算 | 2024 | 8000.0 |

### 3.3 证据溯源

所有抽取字段均携带 `source_evidence_id`（格式：`"p168"`），对应 `evidence_index` 中的页面引用，支持人工核查。

---

## 四、关键技术点

### 4.1 TOC 解析与 block→chapter 映射

- **TOC 页识别**：统计每页点线符号（...、···）密度，≥3 行为 TOC 页
- **层级解析**：正则匹配 L1（第X章/节）、L2（X、）、L3（（X）） 三级标题
- **映射策略**：按页码顺序，每个 block 归属于其页码前最近的 TOC 节点

### 4.2 跨页表格拼接

使用 Jaccard 相似度检测跨页延续表格：

```python
Jaccard(prev_headers, next_headers) ≥ 0.6 → 合并
```

合并时去除第二片段的重复表头行，保留数据行追加至第一片段。

### 4.3 LLM Prompt 工程

**关键设计原则**：
1. `response_format={"type": "json_object"}` 确保 JSON 输出
2. `temperature=0.1` 保持抽取结果稳定性
3. 每个 Prompt 强制要求 `source_evidence_id: "p{页码}"` 格式
4. 财务指标要求 `field_scope` 消歧，避免同名指标混淆
5. 持股比例要求小数表示（0.2356 = 23.56%）

---

## 五、运行环境

| 组件 | 版本 |
|------|------|
| Python | 3.11 |
| MinerU | 3.1.14 |
| DeepSeek API | deepseek-chat |
| FastAPI | 最新 |
| Pydantic | ≥2.0 |

### 本地运行（开发/演示）

```bash
# 1. 激活环境
source .venv/bin/activate

# 2. 配置 API Key
echo "DEEPSEEK_API_KEY=sk-xxx" >> .env

# 3. 启动 Demo
./start_demo.sh
```

### 批量生产（GPU 服务器）

```bash
# Phase 1: MinerU 批量解析（可并行多 GPU）
python batch/batch_parse.py --pdf-dir data/raw_pdfs

# Phase 2: LLM 批量抽取
python batch/run_batch.py
```

---

## 六、输出样例

```json
{
  "document_id": "000064_20190611_31LJ_867634ab",
  "document_type": "招股说明书",
  "issuer_profile": {
    "issuer_name": "XXXX股份有限公司",
    "exchange": "深交所",
    "board": "创业板",
    "legal_representative": "张三",
    "registered_capital": {"value": 50000.0, "unit": "万元", "currency": "CNY"},
    "source_evidence_id": "p15"
  },
  "financials": [
    {
      "field_name": "营业收入",
      "field_scope": "合并利润表",
      "period": "2018-12-31",
      "value": 123456.78,
      "unit": "万元",
      "source_evidence_id": "p168"
    }
  ],
  "evidence_index": [
    {
      "evidence_id": "ev_0001",
      "page_no": 15,
      "chapter": "第一节 发行人基本情况",
      "block_type": "text",
      "quote": "XXXX股份有限公司，注册资本5亿元..."
    }
  ]
}
```

---

*本项目源码：`~/Desktop/finance-due-diligence/`*
