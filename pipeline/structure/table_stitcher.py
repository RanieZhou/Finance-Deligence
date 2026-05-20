"""
跨页表格拼接：检测被分页截断的表格并合并为单一表格对象。
策略：若相邻页的第一个 table block 与上一页最后一个 table block
表头相似（Jaccard ≥ 0.6），则合并。
"""
from __future__ import annotations
import re
from pipeline.parser.mineru_parser import Block, ParsedDocument


def stitch_tables(doc: ParsedDocument) -> list[Block]:
    """
    返回去重后的 block 列表，跨页表格已合并。
    合并后的 block 使用第一个片段的 block_id，page_no 保留起始页。
    """
    blocks = list(doc.blocks)
    merged_ids: set[str] = set()
    result: list[Block] = []

    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.block_id in merged_ids or block.block_type != "table":
            result.append(block)
            i += 1
            continue

        # 尝试向后合并同属一张表的跨页片段
        combined_text = block.text
        j = i + 1
        while j < len(blocks):
            next_b = blocks[j]
            if next_b.block_type != "table":
                break
            if next_b.page_no > block.page_no + 2:
                # 间隔超过2页，认为是不同表格
                break
            if _is_continuation(combined_text, next_b.text):
                combined_text = _merge_html(combined_text, next_b.text)
                merged_ids.add(next_b.block_id)
                j += 1
            else:
                break

        merged_block = Block(
            block_id=block.block_id,
            page_no=block.page_no,
            block_type="table",
            text=combined_text,
            bbox=block.bbox,
            raw=block.raw,
        )
        result.append(merged_block)
        i = j

    return result


def _is_continuation(prev_html: str, next_html: str) -> bool:
    """判断 next 是否是 prev 表格的延续（相同表头）"""
    prev_headers = _extract_headers(prev_html)
    next_headers = _extract_headers(next_html)
    if not prev_headers or not next_headers:
        return False
    intersection = prev_headers & next_headers
    union = prev_headers | next_headers
    jaccard = len(intersection) / len(union) if union else 0
    return jaccard >= 0.6


def _extract_headers(html: str) -> set[str]:
    """提取表格第一行的单元格文本集合"""
    # 匹配 <th> 或第一行 <td>
    th_matches = re.findall(r"<th[^>]*>(.*?)</th>", html, re.DOTALL)
    if th_matches:
        return {_clean(t) for t in th_matches if _clean(t)}

    # 降级：取第一个 <tr> 里的 <td>
    first_row = re.search(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    if first_row:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", first_row.group(1), re.DOTALL)
        return {_clean(t) for t in tds if _clean(t)}

    return set()


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _merge_html(prev: str, next_html: str) -> str:
    """
    合并两段表格 HTML：去掉 next 的表头行（第一个 <tr>），
    将剩余数据行追加到 prev 的 </tbody> 或 </table> 前。
    """
    # 去掉 next 的第一个 <tr>（表头）
    body_rows = re.sub(r"<tr[^>]*>.*?</tr>", "", next_html, count=1, flags=re.DOTALL)
    # 提取剩余 <tr> 行
    rows = re.findall(r"<tr[^>]*>.*?</tr>", body_rows, re.DOTALL)
    if not rows:
        return prev

    insert = "\n".join(rows)
    for tag in ("</tbody>", "</table>"):
        if tag in prev:
            return prev.replace(tag, insert + "\n" + tag, 1)
    return prev + "\n" + insert
