"""
Layer 5: 后处理与业务校验
- 格式归一化（日期/金额/比例）
- 业务规则校验
- 证据索引构建
"""
from __future__ import annotations
import re
from loguru import logger
from schemas.models import DocumentResult, EvidenceItem, FinancialItem

# 财务字段名归一化（post-processing 层补充，覆盖 LLM 输出中的异名）
_FINANCIAL_FIELD_NORMALIZE: dict[str, str] = {
    '扣非净利润':          '扣非归母净利润',
    '扣非归母净利润':      '扣非归母净利润',
    '归属于母公司所有者的净利润': '归母净利润',
    '归属于母公司股东的净利润':   '归母净利润',
    '归母净利润':          '归母净利润',
    '资产总额':            '总资产',
    '资产总计':            '总资产',
    '负债总额':            '总负债',
    '负债总计':            '总负债',
    '负债合计':            '总负债',
    '经营活动产生的现金流量净额': '经营活动现金流净额',
    '经营活动现金流量净额': '经营活动现金流净额',
    '营业总收入':          '营业收入',
}


# ── 日期归一化 ────────────────────────────────────────────
_DATE_PATTERNS = [
    (re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"), r"\1-\2-\3"),
    (re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),     r"\1-\2-\3"),
    (re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})"),   r"\1-\2-\3"),
]


def normalize_date(s: str) -> str:
    for pat, repl in _DATE_PATTERNS:
        m = pat.search(s)
        if m:
            parts = [m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)]
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
    return s


def normalize_document(doc: DocumentResult) -> DocumentResult:
    """对整个文档结果做格式归一化"""
    # 发行人日期
    if doc.issuer_profile.establishment_date:
        doc.issuer_profile.establishment_date = normalize_date(
            doc.issuer_profile.establishment_date
        )

    # 财务指标 period + field_name 归一化
    for item in doc.financials:
        if item.period:
            item.period = normalize_date(item.period)
        item.field_name = _FINANCIAL_FIELD_NORMALIZE.get(item.field_name, item.field_name)

    # 财务核心指标去重（归一化后同一 key 只保留第一条）
    seen: set[tuple] = set()
    deduped: list[FinancialItem] = []
    for item in doc.financials:
        key = (item.field_name, item.field_scope, item.period)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    doc.financials = deduped

    # 合规事项日期
    for item in doc.compliance_items:
        if item.occurrence_date:
            item.occurrence_date = normalize_date(item.occurrence_date)

    # 募投项目：建设期为"/"时清空（表示不适用）
    for proj in doc.fund_raising_projects:
        if proj.construction_period in ('/', '—', '-', ''):
            proj.construction_period = ""

    return doc


# ── 业务规则校验 ──────────────────────────────────────────
def validate_document(doc: DocumentResult) -> list[str]:
    """
    返回警告列表（不阻断输出，仅记录供人工复核）。
    """
    warnings = []

    # 1. 股东持股比例合法性（百分比数值，应在 0-100 之间）
    for sh in doc.ownership_structure.top_shareholders:
        if sh.shareholding_ratio is not None and sh.shareholding_ratio > 100:
            warnings.append(
                f"股东 {sh.name} 持股比例异常: {sh.shareholding_ratio} (应为百分比数值如 23.56)"
            )

    # 2. 募投项目：拟使用募集资金 ≤ 项目总投资
    for proj in doc.fund_raising_projects:
        ti = proj.total_investment.value
        pf = proj.planned_use_of_raised_funds.value
        if ti is not None and pf is not None and pf > ti:
            warnings.append(
                f"募投项目 [{proj.project_name}]: 拟用募资({pf}) > 总投资({ti})"
            )

    # 3. 同一期间同一口径下关键财务指标重复（只检查核心指标）
    seen_financial: set[tuple] = set()
    for item in doc.financials:
        key = (item.field_name, item.field_scope, item.period)
        if key in seen_financial:
            warnings.append(f"财务指标重复: {item.field_name} / {item.field_scope} / {item.period}")
        seen_financial.add(key)

    if warnings:
        for w in warnings:
            logger.warning(f"[校验] {w}")

    return warnings


# ── 证据索引构建 ──────────────────────────────────────────
def build_evidence_index(doc: DocumentResult) -> list[EvidenceItem]:
    """
    从各字段的 source_evidence_id（格式 "p168"）提取页码，
    构建 evidence_index。
    """
    evidence_map: dict[str, EvidenceItem] = {}
    ev_counter = [0]

    def add(evidence_id: str, chapter: str, quote: str, block_type: str = "text"):
        if not evidence_id or evidence_id in evidence_map:
            return
        page_no = _parse_page(evidence_id)
        ev_counter[0] += 1
        ev_id = f"ev_{ev_counter[0]:04d}"
        evidence_map[evidence_id] = EvidenceItem(
            evidence_id=ev_id,
            page_no=page_no,
            chapter=chapter,
            block_type=block_type,
            quote=quote[:200],
        )

    # 发行人
    ip = doc.issuer_profile
    add(ip.source_evidence_id, "发行人基本情况", ip.issuer_name)

    # 股权
    for sh in doc.ownership_structure.controlling_shareholder:
        add(sh.source_evidence_id, "股权结构", sh.name)
    for ac in doc.ownership_structure.actual_controller:
        add(ac.source_evidence_id, "实际控制人", ac.name)

    # 财务
    for fi in doc.financials:
        add(fi.source_evidence_id, fi.chapter,
            f"{fi.field_name} {fi.period} {fi.value}{fi.unit}", "table")

    # 募投
    for fp in doc.fund_raising_projects:
        add(fp.source_evidence_id, "募集资金运用", fp.project_name)

    # 风险
    for ri in doc.risk_items:
        add(ri.source_evidence_id, "风险因素", ri.risk_title)

    # 合规
    for ci in doc.compliance_items:
        add(ci.source_evidence_id, ci.item_type, ci.description)

    return list(evidence_map.values())


def _parse_page(evidence_id: str) -> int:
    m = re.search(r"\d+", evidence_id)
    return int(m.group()) if m else 0


def remap_evidence_ids(doc: DocumentResult) -> DocumentResult:
    """
    将各字段的 source_evidence_id（"p{N}"）替换为 evidence_index 中的 ev_xxxx。
    必须在 build_evidence_index() 之后调用。
    """
    if not doc.evidence_index:
        return doc

    # 建立 page_no → ev_id 反向映射
    page_to_ev: dict[int, str] = {}
    for ev in doc.evidence_index:
        if ev.page_no not in page_to_ev:
            page_to_ev[ev.page_no] = ev.evidence_id

    def remap(raw_id: str) -> str:
        if not raw_id:
            return raw_id
        page = _parse_page(raw_id)
        return page_to_ev.get(page, raw_id)

    doc.issuer_profile.source_evidence_id = remap(doc.issuer_profile.source_evidence_id)

    for sh in doc.ownership_structure.controlling_shareholder:
        sh.source_evidence_id = remap(sh.source_evidence_id)
    for ac in doc.ownership_structure.actual_controller:
        ac.source_evidence_id = remap(ac.source_evidence_id)
    for sh in doc.ownership_structure.top_shareholders:
        sh.source_evidence_id = remap(sh.source_evidence_id)

    for fi in doc.financials:
        fi.source_evidence_id = remap(fi.source_evidence_id)

    for fp in doc.fund_raising_projects:
        fp.source_evidence_id = remap(fp.source_evidence_id)

    for ri in doc.risk_items:
        ri.source_evidence_id = remap(ri.source_evidence_id)

    for ci in doc.compliance_items:
        ci.source_evidence_id = remap(ci.source_evidence_id)

    return doc
