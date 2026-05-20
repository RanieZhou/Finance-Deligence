"""
Layer 4: LLM 字段抽取
对每个 target 的 SectionChunk 调用 LLM，返回对应 Schema 对象。
"""
from __future__ import annotations
from loguru import logger
from pipeline.router.section_router import SectionChunk
from pipeline.extractor.llm_client import extract_json
from pipeline.extractor.prompts import SYSTEM_PROMPTS
from schemas.models import (
    IssuerProfile, OwnershipStructure, FinancialItem,
    FundRaisingProject, RiskItem, ComplianceItem,
    ControllingShareholder, TopShareholder, ActualController, Money,
)


def extract_issuer(chunks: list[SectionChunk]) -> IssuerProfile:
    if not chunks:
        return IssuerProfile()
    text = _merge_chunks(chunks)
    raw = extract_json(SYSTEM_PROMPTS["issuer_profile"], text)
    return _parse_issuer(raw)


def extract_ownership(chunks: list[SectionChunk]) -> OwnershipStructure:
    if not chunks:
        return OwnershipStructure()
    text = _merge_chunks(chunks)
    raw = extract_json(SYSTEM_PROMPTS["ownership_structure"], text)
    return _parse_ownership(raw)


def extract_financials(chunks: list[SectionChunk]) -> list[FinancialItem]:
    if not chunks:
        return []
    results = []
    for chunk in chunks:
        raw = extract_json(SYSTEM_PROMPTS["financials"], chunk.text)
        items = raw.get("financials", [])
        for item in items:
            try:
                results.append(FinancialItem(
                    field_name=item.get("field_name", ""),
                    field_scope=item.get("field_scope", chunk.chapter),
                    period=item.get("period", ""),
                    value=_to_float(item.get("value")),
                    unit=item.get("unit", "万元"),
                    currency=item.get("currency", "CNY"),
                    chapter=item.get("chapter", chunk.chapter),
                    source_evidence_id=item.get("source_evidence_id", ""),
                ))
            except Exception as e:
                logger.warning(f"FinancialItem parse error: {e}")
    return results


def extract_fund_raising(chunks: list[SectionChunk]) -> list[FundRaisingProject]:
    if not chunks:
        return []
    text = _merge_chunks(chunks)
    raw = extract_json(SYSTEM_PROMPTS["fund_raising_projects"], text)
    results = []
    for item in raw.get("fund_raising_projects", []):
        try:
            results.append(FundRaisingProject(
                project_name=item.get("project_name", ""),
                project_type=item.get("project_type", ""),
                total_investment=_parse_money(item.get("total_investment", {})),
                planned_use_of_raised_funds=_parse_money(item.get("planned_use_of_raised_funds", {})),
                construction_period=item.get("construction_period", ""),
                implementation_entity=item.get("implementation_entity", ""),
                source_evidence_id=item.get("source_evidence_id", ""),
            ))
        except Exception as e:
            logger.warning(f"FundRaisingProject parse error: {e}")
    return results


def extract_risks(chunks: list[SectionChunk]) -> list[RiskItem]:
    if not chunks:
        return []
    text = _merge_chunks(chunks)
    raw = extract_json(SYSTEM_PROMPTS["risk_items"], text)
    results = []
    for item in raw.get("risk_items", []):
        try:
            results.append(RiskItem(
                risk_title=item.get("risk_title", ""),
                risk_category=item.get("risk_category", ""),
                risk_description=item.get("risk_description", ""),
                severity_level=item.get("severity_level", ""),
                source_evidence_id=item.get("source_evidence_id", ""),
            ))
        except Exception as e:
            logger.warning(f"RiskItem parse error: {e}")
    return results


def extract_compliance(chunks: list[SectionChunk]) -> list[ComplianceItem]:
    if not chunks:
        return []
    text = _merge_chunks(chunks)
    raw = extract_json(SYSTEM_PROMPTS["compliance_items"], text)
    results = []
    for item in raw.get("compliance_items", []):
        try:
            results.append(ComplianceItem(
                item_type=item.get("item_type", ""),
                counterparty=item.get("counterparty", ""),
                occurrence_date=item.get("occurrence_date", ""),
                period=item.get("period", ""),
                amount=_parse_money(item.get("amount", {})),
                description=item.get("description", ""),
                source_evidence_id=item.get("source_evidence_id", ""),
            ))
        except Exception as e:
            logger.warning(f"ComplianceItem parse error: {e}")
    return results


# ── 内部辅助 ──────────────────────────────────────────────

def _merge_chunks(chunks: list[SectionChunk], max_chars: int = 12000) -> str:
    parts = [f"[章节: {c.chapter}]\n{c.text}" for c in chunks]
    text = "\n\n".join(parts)
    return text[:max_chars]


def _parse_money(d: dict) -> Money:
    if not isinstance(d, dict):
        return Money()
    return Money(
        value=_to_float(d.get("value")),
        unit=d.get("unit", "万元"),
        currency=d.get("currency", "CNY"),
    )


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("，", ""))
    except (ValueError, TypeError):
        return None


def _parse_issuer(raw: dict) -> IssuerProfile:
    return IssuerProfile(
        issuer_name=raw.get("issuer_name", ""),
        issuer_name_normalized=raw.get("issuer_name_normalized", ""),
        stock_code=raw.get("stock_code", ""),
        exchange=raw.get("exchange", ""),
        board=raw.get("board", ""),
        legal_representative=raw.get("legal_representative", ""),
        establishment_date=raw.get("establishment_date", ""),
        registered_capital=_parse_money(raw.get("registered_capital", {})),
        registered_address=raw.get("registered_address", ""),
        industry=raw.get("industry", ""),
        main_business=raw.get("main_business", ""),
        source_evidence_id=raw.get("source_evidence_id", ""),
    )


def _parse_ownership(raw: dict) -> OwnershipStructure:
    controlling = []
    for s in (raw.get("controlling_shareholder") or []):
        controlling.append(ControllingShareholder(
            name=s.get("name", ""),
            shareholding_ratio=_to_float(s.get("shareholding_ratio")),
            direct_or_indirect=s.get("direct_or_indirect", ""),
            source_evidence_id=s.get("source_evidence_id", ""),
        ))

    top = []
    for s in (raw.get("top_shareholders") or []):
        rank_val = s.get("rank")
        top.append(TopShareholder(
            name=s.get("name", ""),
            shareholding_ratio=_to_float(s.get("shareholding_ratio")),
            rank=int(rank_val) if rank_val is not None else None,
            source_evidence_id=s.get("source_evidence_id", ""),
        ))

    controllers = []
    for c in (raw.get("actual_controller") or []):
        controllers.append(ActualController(
            name=c.get("name", ""),
            control_type=c.get("control_type", ""),
            source_evidence_id=c.get("source_evidence_id", ""),
        ))

    return OwnershipStructure(
        controlling_shareholder=controlling,
        actual_controller=controllers,
        concerted_action_flag=bool(raw.get("concerted_action_flag", False)),
        top_shareholders=top,
    )
