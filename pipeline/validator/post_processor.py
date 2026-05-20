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

    # 财务指标 period
    for item in doc.financials:
        if item.period:
            item.period = normalize_date(item.period)

    # 合规事项日期
    for item in doc.compliance_items:
        if item.occurrence_date:
            item.occurrence_date = normalize_date(item.occurrence_date)

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

    # 3. 同一期间同一口径下关键财务指标重复
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
