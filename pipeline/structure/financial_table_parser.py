"""
财务表格规则解析器
将 MinerU 输出的 HTML 表格直接解析为结构化财务指标，不依赖 LLM。
适用于合并资产负债表、合并利润表、合并现金流量表等标准财务报表。
"""
from __future__ import annotations
import re
from html.parser import HTMLParser
from typing import Optional

from loguru import logger
from pipeline.parser.mineru_parser import Block
from pipeline.structure.toc_parser import DocumentStructure
from schemas.models import FinancialItem, Money


# ── HTML 表格解析 ──────────────────────────────────────────
class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell_buf: list[str] = []
        self._depth = 0
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self._depth += 1
            if self._depth == 1:
                self.rows = []
                self._row = []
        elif tag == 'tr' and self._depth == 1:
            self._row = []
        elif tag in ('td', 'th') and self._depth == 1:
            self._in_cell = True
            self._cell_buf = []

    def handle_endtag(self, tag):
        if tag == 'table':
            self._depth -= 1
        elif tag == 'tr' and self._depth == 1:
            if any(c.strip() for c in self._row):
                self.rows.append(self._row[:])
        elif tag in ('td', 'th') and self._depth == 1:
            self._row.append(''.join(self._cell_buf).strip())
            self._in_cell = False
            self._cell_buf = []

    def handle_data(self, data):
        if self._in_cell and self._depth == 1:
            self._cell_buf.append(data)


def _extract_rows(html: str) -> list[list[str]]:
    p = _TableParser()
    try:
        p.feed(html)
    except Exception:
        pass
    return p.rows


# ── 报告期识别 ────────────────────────────────────────────
_PERIOD_PATTERNS: list[tuple] = [
    (re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日'),
     lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"),
    (re.compile(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})'),
     lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"),
    (re.compile(r'(\d{4})年(\d{1,2})-(\d{1,2})月'),
     lambda m: f"{m.group(1)}-{int(m.group(3)):02d}-30"),
    (re.compile(r'(\d{4})年(\d{1,2})月'),
     lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-30"),
    (re.compile(r'(\d{4})年度?\s*$'),
     lambda m: f"{m.group(1)}-12-31"),
    (re.compile(r'^(\d{4})\s*$'),
     lambda m: f"{m.group(1)}-12-31"),
]


def _detect_period(cell: str) -> Optional[str]:
    for pat, fmt in _PERIOD_PATTERNS:
        m = pat.search(cell.strip())
        if m:
            return fmt(m)
    return None


# ── 数值解析 ──────────────────────────────────────────────
def _parse_number(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.strip().replace(',', '').replace('，', '').replace(' ', '').replace('\xa0', '')
    if not s or s in ('—', '-', '－', '/', '\\', ''):
        return None
    neg = False
    if (s.startswith('(') and s.endswith(')')) or (s.startswith('（') and s.endswith('）')):
        neg = True
        s = s[1:-1]
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None


# ── 单位检测 ──────────────────────────────────────────────
_UNIT_PAT = re.compile(r'单位[：:]\s*(元|万元|亿元|千元|百万元)')

_UNIT_MULTIPLIER = {
    '元':    1 / 10000,
    '万元':  1.0,
    '亿元':  10000.0,
    '千元':  0.1,
    '百万元': 100.0,
}


def _detect_unit(table_text: str, sample_values: list[float] | None = None) -> tuple[str, float]:
    m = _UNIT_PAT.search(table_text[:800])
    if m:
        u = m.group(1)
        return '万元', _UNIT_MULTIPLIER.get(u, 1.0)
    # 无显式单位标注时，根据数值量级自适应推断
    # 若中位数绝对值 > 500000，判定为元单位（如 450,246,597），转换为万元
    if sample_values:
        pos = sorted(abs(v) for v in sample_values if v != 0)
        if pos and pos[len(pos) // 2] > 500_000:
            return '万元', 1 / 10_000
    return '万元', 1.0


# ── 字段名规范化 ──────────────────────────────────────────
_FIELD_NORMALIZE = {
    '归属于母公司所有者的净利润':                '归母净利润',
    '归属于母公司股东的净利润':                  '归母净利润',
    '归属母公司净利润':                          '归母净利润',
    '归属于母公司所有者的综合收益总额':           '归母净利润',
    '扣除非经常性损益后的净利润':                '扣非归母净利润',
    '扣非净利润':                               '扣非归母净利润',   # 招股说明书中通常与归母口径一致
    '扣除非经常性损益后归属于母公司股东的净利润': '扣非归母净利润',
    '扣除非经常性损益后归属于母公司所有者的净利润': '扣非归母净利润',
    '研究开发费用':                              '研发费用',
    '资产总计':                                  '总资产',
    '资产总额':                                  '总资产',
    '负债总计':                                  '总负债',
    '负债合计':                                  '总负债',
    '经营活动产生的现金流量净额':                '经营活动现金流净额',
    '经营活动现金流量净额':                      '经营活动现金流净额',
    '营业总收入':                                '营业收入',
    '一、营业收入':                              '营业收入',
}

_STRIP_PREFIX = re.compile(
    r'^(?:[一二三四五六七八九十百\d]+[、．.\s]+|[（\(][一二三四五六七八九十\d]+[）\)]\s*|(?:减|加|其中|含|包括)[：:]\s*)'
)

_FINANCIAL_KEYWORDS = re.compile(
    r'营业收入|净利润|总资产|总负债|现金流|研发费用|毛利|营业成本|所有者权益|资产负债|利润表'
)

_SCOPE_KEYWORDS = {
    '合并资产负债表': re.compile(r'资产负债'),
    '合并利润表':     re.compile(r'利润表|利润|营业收入'),
    '合并现金流量表': re.compile(r'现金流'),
}

# 噪声字段模式：纯数字（行号）、空白、标点
_NOISE_FIELD_PAT = re.compile(r'^[\d\s,，.。、；：:]+$')
_SUBTOTAL_EXACT = {'合计', '小计', '其他', '境内', '境外', '其他业务'}

# 每股/比率字段模式（不参与万元转换）
_PER_SHARE_PAT = re.compile(r'每股|/股|每基金份额')
_RATIO_PAT = re.compile(r'\(%\)|（%）|率$|比例$|占.*收入|毛利率|净利率|收益率|负债率|增长率')

# 字段名内嵌单位，如 "单位价格(元/台)" → "元/台"
_INLINE_UNIT_PAT = re.compile(r'[（(]([元万亿千百]元?[/／][^\s）)]{1,8}|%|元/股)[）)]')

# 字段→报表口径映射（优先于表格级 scope 推断）
_FIELD_SCOPE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'营业收入|归母净利润|扣非|净利润|营业成本|毛利(?!率)|管理费|销售费|研发费用|财务费用|利润总额|所得税'), '合并利润表'),
    (re.compile(r'经营活动现金流|经营活动产生|投资活动|筹资活动|现金及现金等价物'), '合并现金流量表'),
    (re.compile(r'净资产收益率|每股收益|每股净资产|每股经营活动'), '主要财务指标'),
    (re.compile(r'总资产|总负债|所有者权益|净资产(?!收益率)|应收账款|应付账款|存货|流动资产|流动负债|货币资金'), '合并资产负债表'),
]


def _is_noise_field(field_name: str) -> bool:
    s = field_name.strip()
    if not s or len(s) < 2:
        return True
    if _NOISE_FIELD_PAT.match(s):
        return True
    if s in _SUBTOTAL_EXACT:
        return True
    try:
        float(s.replace(',', '').replace('，', ''))
        return True  # 纯数字字符串（行号）
    except ValueError:
        pass
    return False


def _field_unit(field_name: str, table_unit: str) -> str:
    # 字段名内嵌单位最优先（如"单位价格(元/台)"）
    m = _INLINE_UNIT_PAT.search(field_name)
    if m:
        return m.group(1)
    if _PER_SHARE_PAT.search(field_name):
        return '元/股'
    if _RATIO_PAT.search(field_name):
        return '%'
    return table_unit


def _override_scope_by_field(field_name: str, default_scope: str) -> str:
    for pat, scope in _FIELD_SCOPE_RULES:
        if pat.search(field_name):
            return scope
    return default_scope


def _clean_field_name(raw: str) -> str:
    s = _STRIP_PREFIX.sub('', raw.strip())
    return _FIELD_NORMALIZE.get(s, s).strip()


def _infer_scope(table_text: str, chapter: str) -> str:
    context = table_text[:300] + " " + chapter
    for scope, pat in _SCOPE_KEYWORDS.items():
        if pat.search(context):
            return scope
    return '合并报表'


# ── 主入口 ────────────────────────────────────────────────
def extract_table_financials(
    blocks: list[Block],
    structure: DocumentStructure,
) -> list[FinancialItem]:
    """
    遍历所有 table block，从财务章节中的表格直接规则化抽取财务指标。
    返回 FinancialItem 列表，与 LLM 结果合并去重后使用。
    """
    results: list[FinancialItem] = []
    financial_chapters = re.compile(
        r'财务会计|财务报表|财务信息|管理层分析|主要财务数据|主要财务指标|经营成果|财务状况'
    )

    for block in blocks:
        if block.block_type != 'table':
            continue
        if not block.text or '<table' not in block.text.lower():
            continue

        chapter = structure.block_chapter_map.get(block.block_id, '')
        if not financial_chapters.search(chapter):
            continue

        items = _parse_one_table(block.text, block.page_no, chapter)
        results.extend(items)

    logger.info(f"Table parser: extracted {len(results)} financial records from tables")
    return results


def _parse_one_table(html: str, page_no: int, chapter: str) -> list[FinancialItem]:
    rows = _extract_rows(html)
    if len(rows) < 2:
        return []

    table_text = ' '.join(c for row in rows for c in row)
    if not _FINANCIAL_KEYWORDS.search(table_text):
        return []

    # 找含有报告期的表头行
    period_cols: list[tuple[int, str]] = []
    header_idx = 0
    for ri, row in enumerate(rows[:5]):
        periods = [(ci, _detect_period(cell)) for ci, cell in enumerate(row)]
        found = [(ci, p) for ci, p in periods if p]
        if len(found) >= 2:
            period_cols = found
            header_idx = ri
            break

    if not period_cols:
        return []

    # 预扫描普通数值字段（排除每股/比率）以推断单位量级
    sample_values: list[float] = []
    for row in rows[header_idx + 1:]:
        if not row:
            continue
        raw_name = row[0] if row else ''
        field = _clean_field_name(raw_name)
        if _is_noise_field(field) or _PER_SHARE_PAT.search(field) or _RATIO_PAT.search(field):
            continue
        for col_idx, _ in period_cols:
            if col_idx < len(row):
                v = _parse_number(row[col_idx])
                if v is not None and v != 0:
                    sample_values.append(v)
        if len(sample_values) >= 20:
            break

    unit, multiplier = _detect_unit(table_text, sample_values)
    scope = _infer_scope(table_text, chapter)

    results: list[FinancialItem] = []
    for row in rows[header_idx + 1:]:
        if not row:
            continue
        raw_name = row[0] if row else ''
        field_name = _clean_field_name(raw_name)
        if not field_name or _is_noise_field(field_name):
            continue

        field_scope = _override_scope_by_field(field_name, scope)
        funit = _field_unit(field_name, unit)
        # 每股/比率字段已是终态单位，不乘换算系数
        fmultiplier = 1.0 if funit != unit else multiplier

        for col_idx, period in period_cols:
            if col_idx >= len(row):
                continue
            value = _parse_number(row[col_idx])
            if value is None:
                continue
            value_converted = round(value * fmultiplier, 4)
            results.append(FinancialItem(
                field_name=field_name,
                field_scope=field_scope,
                period=period,
                value=value_converted,
                unit=funit,
                currency='CNY',
                chapter=chapter,
                source_evidence_id=f'p{page_no}',
            ))

    return results


def merge_financials(
    table_items: list[FinancialItem],
    llm_items: list[FinancialItem],
) -> list[FinancialItem]:
    """
    合并规则抽取（table_items）和 LLM 抽取（llm_items）的结果。
    以 (field_name, field_scope, period) 为去重 key，规则结果优先。
    """
    seen: set[tuple] = set()
    merged: list[FinancialItem] = []

    for item in table_items:
        key = (item.field_name, item.field_scope, item.period)
        if key not in seen:
            seen.add(key)
            merged.append(item)

    for item in llm_items:
        key = (item.field_name, item.field_scope, item.period)
        if key not in seen:
            seen.add(key)
            merged.append(item)

    return merged
