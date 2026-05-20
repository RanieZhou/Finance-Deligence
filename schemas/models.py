"""
金融赛题 - Pydantic Schema 定义
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field


# ── 通用货币金额 ──────────────────────────────────────────
class Money(BaseModel):
    value: Optional[float] = None
    unit: str = "万元"
    currency: str = "CNY"


# ── 1. 证据索引条目 ───────────────────────────────────────
class EvidenceItem(BaseModel):
    evidence_id: str = Field(description="证据唯一ID，如 ev_0001")
    page_no: int = Field(description="来源页码")
    chapter: str = Field(description="所属章节名称")
    block_type: Literal["text", "table", "footnote"] = "text"
    quote: str = Field(description="原文摘要片段（≤200字）")
    bbox: Optional[list[float]] = Field(default=None, description="[x0,y0,x1,y1]")


# ── 2. 发行人基础信息 ─────────────────────────────────────
class IssuerProfile(BaseModel):
    issuer_name: str = ""
    issuer_name_normalized: str = Field(default="", description="统一简称")
    stock_code: str = ""
    exchange: str = Field(default="", description="上交所/深交所/北交所")
    board: str = Field(default="", description="主板/科创板/创业板/北交所")
    legal_representative: str = ""
    establishment_date: str = Field(default="", description="YYYY-MM-DD")
    registered_capital: Money = Field(default_factory=Money)
    registered_address: str = ""
    industry: str = ""
    main_business: str = ""
    source_evidence_id: str = ""


# ── 3. 股权与控制关系 ─────────────────────────────────────
class ControllingShareholder(BaseModel):
    name: str = ""
    shareholding_ratio: Optional[float] = Field(default=None, description="百分比数值，如 23.56 表示 23.56%")
    direct_or_indirect: str = Field(default="", description="直接/间接/直接和间接")
    source_evidence_id: str = ""


class TopShareholder(BaseModel):
    name: str = ""
    shareholding_ratio: Optional[float] = Field(default=None, description="百分比数值，如 23.56 表示 23.56%")
    rank: Optional[int] = Field(default=None, description="持股排名，如 1 表示第一大股东")
    source_evidence_id: str = ""


class ActualController(BaseModel):
    name: str = ""
    control_type: str = Field(default="", description="自然人/国有/外资等")
    source_evidence_id: str = ""


class OwnershipStructure(BaseModel):
    controlling_shareholder: list[ControllingShareholder] = Field(default_factory=list)
    actual_controller: list[ActualController] = Field(default_factory=list)
    concerted_action_flag: bool = False
    top_shareholders: list[TopShareholder] = Field(default_factory=list, description="前十大股东")


# ── 4. 财务指标 ───────────────────────────────────────────
class FinancialItem(BaseModel):
    field_name: str = Field(description="指标名称，如 营业收入")
    field_scope: str = Field(description="口径，如 合并利润表/募投项目预算/管理层分析")
    period: str = Field(default="", description="YYYY-MM-DD 或 YYYY")
    value: Optional[float] = None
    unit: str = "万元"
    currency: str = "CNY"
    chapter: str = Field(default="", description="来源章节")
    source_evidence_id: str = ""


# ── 5. 募投项目 ───────────────────────────────────────────
class FundRaisingProject(BaseModel):
    project_name: str = ""
    project_type: str = Field(default="扩产", description="扩产/研发/补流/偿债等")
    total_investment: Money = Field(default_factory=Money)
    planned_use_of_raised_funds: Money = Field(default_factory=Money)
    construction_period: str = ""
    implementation_entity: str = ""
    source_evidence_id: str = ""


# ── 6. 风险事项 ───────────────────────────────────────────
class RiskItem(BaseModel):
    risk_title: str = ""
    risk_category: str = Field(default="", description="财务风险/市场风险/合规风险/经营风险等")
    risk_description: str = ""
    severity_level: Literal["高", "中", "低", ""] = ""
    source_evidence_id: str = ""


# ── 7. 合规事项（处罚/诉讼/关联交易） ────────────────────
class ComplianceItem(BaseModel):
    item_type: str = Field(description="行政处罚/诉讼仲裁/关联交易/对外担保")
    counterparty: str = ""
    occurrence_date: str = Field(default="", description="YYYY-MM-DD，适用于处罚/诉讼")
    period: str = Field(default="", description="报告期，适用于关联交易，如 2022-12-31")
    amount: Money = Field(default_factory=Money)
    description: str = ""
    source_evidence_id: str = ""


# ── 顶层文档对象 ──────────────────────────────────────────
class DocumentResult(BaseModel):
    document_id: str = Field(description="文件名（不含扩展名）")
    document_type: str = Field(
        default="",
        description="招股说明书/可转债募集说明书/上市公告书/补充披露文件"
    )
    issuer_profile: IssuerProfile = Field(default_factory=IssuerProfile)
    ownership_structure: OwnershipStructure = Field(default_factory=OwnershipStructure)
    financials: list[FinancialItem] = Field(default_factory=list)
    fund_raising_projects: list[FundRaisingProject] = Field(default_factory=list)
    risk_items: list[RiskItem] = Field(default_factory=list)
    compliance_items: list[ComplianceItem] = Field(default_factory=list)
    evidence_index: list[EvidenceItem] = Field(default_factory=list)
