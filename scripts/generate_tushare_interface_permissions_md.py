"""
从 tushare_docs_md + docs/tushare积分权限表.xlsx 生成接口权限矩阵：

- docs/tushare-interface-permissions.md — 表格，便于人工浏览
- docs/tushare-interface-permissions.json — 结构化条目，便于程序与 Agent 检索

用法（仓库根目录）:

  C:/Users/Erich/miniforge3/envs/free/python.exe scripts/generate_tushare_interface_permissions_md.py
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_MD = ROOT / "tushare_docs_md"
INDEX_JSON = DOCS_MD / "INDEX.json"
OUT_MD = ROOT / "docs" / "tushare-interface-permissions.md"
OUT_JSON = ROOT / "docs" / "tushare-interface-permissions.json"

USER_POINTS = 8000

# 摘自 docs/tushare积分权限表.xlsx 「单独权限」等产品线（具体以官网为准）
SEPARATE_API_PREFIX: dict[str, str] = {
    # 包月 RT
    "rt_k": "200元/月（单独·A股日线RT）",
    "rt_etf_k": "200元/月（单独·ETF日线RT）",
    "rt_etf_sz_iopv": "300元/月（单独·深圳ETF IOPV）",
    "rt_idx_k": "200元/月（单独·指数日线RT）",
    "rt_hk_k": "1000元/月（单独·港股日线RT）",
    "rt_min": "1000元/月（单独·A股分钟RT）",
    "rt_fut_min": "1000元/月（单独·期货分钟RT）",
}


def separate_price_for_api(api: str, crumb: str) -> str | None:
    """按接口名 + 文档分类路径，挂载积分权限表中的「单独购买」参考价。"""
    if api in SEPARATE_API_PREFIX:
        return SEPARATE_API_PREFIX[api]
    if api == "news":
        return "1000元/年（单独·新闻资讯套餐）"
    if api == "major_news":
        return "1000元/年（单独·新闻资讯套餐）"
    if api == "cctv_news":
        return "1000元/年（单独·新闻联播文字稿等同套餐，以官网为准）"
    if api == "ann":
        return "1000元/年（单独·公司公告）"
    if api == "std_policy":
        return "1000元/年（单独·政策法规库）"
    if api == "report_rc":
        return "500元/年（单独·券商研报）"
    if api in {"irm_qa_sh", "irm_qa_sz"}:
        return "500元/年（单独·董秘互动回复）"
    if api == "stk_mins":
        if "ETF" in crumb:
            return "2000元/年（单独·ETF历史分钟）"
        return "2000元/年（单独·股票历史分钟）"
    if api == "ft_mins":
        return "2000元/年（单独·期货历史分钟）"
    if api == "opt_mins":
        return "2000元/年（单独·期权历史分钟）"
    if api == "hk_mins":
        return "2000元/年（单独·港股历史分钟）"
    if api in {"hk_daily", "hk_daily_adj"}:
        return "1000元/年（单独·港股历史日线）"
    if api in {"us_daily", "us_daily_adj"}:
        return "2000元/年（单独·美股历史日线）"
    if api == "cb_price_chg":
        return "500元/年（单独·可转债价格变动）"
    if api == "stk_premarket":
        return "500元/年（单独·盘前股本情况）"
    if api == "stk_auction":
        return "500元/年（单独·盘前集合竞价，或与分钟类产品组合见官网）"
    if api in {"stk_auction_o", "stk_auction_c"}:
        return "依附「股票历史分钟」等产品（参见官网权限说明，约2000元/年）"
    if api in {
        "hk_balancesheet",
        "hk_income",
        "hk_cashflow",
        "hk_fina_indicator",
    }:
        return "500元/年（单独·港股财报，或15000积分，官网为准）"
    if api in {
        "us_balancesheet",
        "us_income",
        "us_cashflow",
        "us_fina_indicator",
    }:
        return "500元/年（单独·美股财报，或15000积分，官网为准）"
    if api == "hk_adjfactor":
        return "随「港股历史日线」权限（约1000元/年，官网为准）"
    if api == "us_adjfactor":
        return "随「美股历史日线」权限（约2000元/年，官网为准）"
    if api == "rt_min_daily":
        return "随「A股分钟RT」等权限（约1000元/月，官网为准）"
    return None


def strip_md_cell(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("*", "").strip())


def extract_apis(interface_line: str) -> list[str]:
    """从「接口：」行提取接口名列表。"""
    m = re.search(r"接口[：:]", interface_line)
    if not m:
        return []
    rest = interface_line[m.end() :].strip()
    # 截止到「描述」或句号前的主干
    for sep in ("描述", "。"):
        if sep in rest:
            rest = rest.split(sep, 1)[0].strip()
    # 拆分多个接口：逗号 / 中文逗号 / 「可以通过」前的首个
    rest = rest.split("可以通过")[0].strip()
    rest = rest.split("可以通过[**")[0].strip()
    pieces = re.split(r"[,，]\s*", rest)
    out: list[str] = []
    for p in pieces:
        p = p.strip().strip("，").strip()
        if not p:
            continue
        # 去掉「等非 pro」噪音
        p = re.split(r"\s+", p)[0]
        # 只允许类似 pro_api_name 的 token
        token = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)", p)
        if token:
            out.append(token.group(1))
    return list(dict.fromkeys(out))


def parse_output_fields(section: str) -> list[str]:
    """解析「输出参数」Markdown 表格第一列字段名。"""
    m = re.search(
        r"####\s*输出参数\s*([\s\S]*?)(?=\n####\s|\Z)", section, re.MULTILINE
    )
    if not m:
        return []
    block = m.group(1)
    rows: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [strip_md_cell(c) for c in line.split("|")]
        parts = [c for c in parts if c]
        if len(parts) < 2:
            continue
        if parts[0] in {"名称", "名称 ", "数据源"}:
            continue
        if set(parts[0]) <= {"-", " "} or parts[0] == "---":
            continue
        fname = parts[0]
        # 跳过说明性子表头
        if fname in {"参数", "属性"}:
            continue
        if re.match(r"^[a-z][a-z0-9_.]*$", fname, re.I):
            rows.append(fname)
        elif "_" in fname and not fname.startswith("http"):
            rows.append(fname)
    return list(dict.fromkeys(rows))


_RE_POINTS = re.compile(r"(\d+)\s*积分")


def infer_min_points(perm_blob: str, apis: list[str]) -> int | None:
    nums = [int(x) for x in _RE_POINTS.findall(perm_blob)]
    nums.extend(int(m.group(1)) for m in re.finditer(r"积分达到\s*(\d+)", perm_blob))
    nums.extend(int(m.group(1)) for m in re.finditer(r"(?:需要|积累|累积|具备|达到)(?:至少)?\s*(\d+)\s*积分", perm_blob))
    if nums:
        # 「120积分可以调取2次」等为试用档位，但真正门槛通常另有说明
        filtered = [n for n in nums if n >= 500]
        if filtered:
            return min(filtered)
        return min(nums)
    # A 股日线等常用接口文档只写「基础积分」，对照积分权限表免费档视为 120
    if "基础积分" in perm_blob and apis == ["daily"]:
        return 120
    return None


def is_separate_by_text(perm_blob: str) -> bool:
    keys = (
        "单独开通",
        "需单独",
        "单独开权限",
        "另购",
        "跟积分没有关系",
        "跟积分没关系",
        "与积分无关",
        "单独的权限接口",
    )
    return any(k in perm_blob for k in keys)


def permission_blob_from_text(text: str) -> str:
    """取文首说明区（通常在第一个 #### 输入/输出 之前），用于权限解析。"""
    m = re.search(r"^[ \t]*####\s+", text, re.MULTILINE)
    if m:
        return text[: m.start()]
    return text[:4000]


def is_leaf_interface_doc(md_path_posix: str) -> bool:
    """仅「叶子」`data.md`：所在目录下没有任何子文件夹（上级目录的 md 多为专题索引，非单个接口文档）。"""
    abs_dir = ROOT / Path(md_path_posix).parent
    if not abs_dir.is_dir():
        return False
    return not any(p.is_dir() for p in abs_dir.iterdir())


def cell_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").strip()


@dataclass
class Row:
    doc_id: str
    md_path_posix: str
    crumb: str
    title_md: str
    api_guess: str | None
    apis: list[str]
    fields: list[str]
    perm_blob: str
    min_points: int | None
    separate_doc: bool
    separate_sheet: str | None


@dataclass(frozen=True)
class AvailabilityEval:
    """程序化筛选用 `code`；展示用 `label_zh`。"""

    code: str
    label_zh: str


def evaluate_availability(r: Row, user_pts: int = USER_POINTS) -> AvailabilityEval:
    if r.separate_sheet:
        if r.separate_sheet.startswith(("随「", "依附「")):
            return AvailabilityEval(
                "needs_parent_license_bundle",
                "否（依赖其他付费权限）",
            )
        return AvailabilityEval(
            "needs_separate_addon",
            "否（需单独购买或未订阅）",
        )
    if r.separate_doc:
        return AvailabilityEval(
            "needs_separate_addon",
            "否（需单独购买或未订阅）",
        )
    if r.min_points is None:
        return AvailabilityEval(
            "unknown_points_gate",
            "待核对（文档未解析到明确积分门槛）",
        )
    if r.min_points <= user_pts:
        return AvailabilityEval("ok_points_gate_only", "是")
    return AvailabilityEval(
        "insufficient_points",
        f"否（文档门槛 {r.min_points} 积分）",
    )


def availability(r: Row) -> str:
    return evaluate_availability(r).label_zh


def entry_json(r: Row) -> dict:
    ev = evaluate_availability(r)
    blob = " ".join(r.perm_blob.replace("\r", "").split())
    excerpt = ""
    if blob:
        excerpt = blob[:800] + ("…" if len(blob) > 800 else "")
    sep_col: str | None = None
    if r.separate_sheet:
        sep_col = r.separate_sheet
    elif r.separate_doc:
        sep_col = "是（详见权限原文／官网单品）"
    api_list = list(r.apis)
    primary_api = api_list[0] if len(api_list) == 1 else None
    return {
        "doc_id": r.doc_id,
        "md_path_posix": r.md_path_posix,
        "tushare_document_url": f"https://tushare.pro/document/2?doc_id={r.doc_id}",
        "breadcrumb_zh": r.crumb or None,
        "title_md": r.title_md or None,
        "pro_api_guess": r.api_guess,
        "apis": api_list,
        "primary_api": primary_api,
        "output_fields": list(r.fields),
        "min_points_inferred": r.min_points,
        "separate_permission_in_doc": r.separate_doc,
        "separate_product_hint_zh": r.separate_sheet,
        "separate_license_column_zh": sep_col,
        "availability": {
            "code": ev.code,
            "label_zh": ev.label_zh,
        },
        "permission_excerpt_zh": excerpt or None,
    }


def collect_rows() -> list[Row]:
    data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    entries = data["entries"]
    rows: list[Row] = []
    for ent in entries:
        doc_id = str(ent["doc_id"])
        rel = Path(ent["md_path_posix"])
        if not is_leaf_interface_doc(ent["md_path_posix"]):
            continue
        path = ROOT / rel
        crumb = "/".join(ent.get("breadcrumb_zh") or [])
        title_md = ent.get("markdown_first_heading") or ent.get("menu_leaf_zh") or ""
        api_guess = ent.get("pro_api_name_guess")
        if not path.exists():
            continue
        md_path_posix = str(ent["md_path_posix"])
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            rows.append(
                Row(
                    doc_id,
                    md_path_posix,
                    crumb,
                    title_md,
                    api_guess,
                    [],
                    [],
                    "",
                    None,
                    False,
                    None,
                )
            )
            continue
        perm_blob = permission_blob_from_text(raw)
        # 接口行：含「接口：」的该行常在同一段说明里
        api_line_match = re.search(r"^.*接口[：：].*$", raw, re.MULTILINE)
        apis = extract_apis(api_line_match.group(0)) if api_line_match else []
        if not apis and api_guess:
            apis = [api_guess]
        fields = parse_output_fields(raw)
        separate_doc = is_separate_by_text(perm_blob)
        mp = infer_min_points(perm_blob, apis)

        sep_sheet = None
        for a in apis:
            sep_sheet = separate_price_for_api(a, crumb)
            if sep_sheet:
                break

        rows.append(
            Row(
                doc_id,
                md_path_posix,
                crumb,
                title_md,
                api_guess,
                apis,
                fields,
                perm_blob,
                mp,
                separate_doc,
                sep_sheet,
            )
        )
    rows.sort(key=lambda r: (r.crumb, r.doc_id))
    return rows


def main() -> None:
    rows = collect_rows()
    lines: list[str] = []
    gen_time = Path(__file__).stat().st_mtime_ns
    lines.append("# Tushare 接口字段与权限一览")
    lines.append("")
    lines.append("本文件根据本地 **`tushare_docs_md`** 各页 `data.md` 解析生成，并用 **`docs/tushare积分权限表.xlsx`** 中的「单独权限」产品与定价做交叉核对；**不等同于官网实时口径**，接入前仍以 [Tushare 官网](https://tushare.pro) 与用户当前账号权限为准。")
    lines.append("")
    lines.append("## 维护说明")
    lines.append("")
    lines.append("- **重新生成**：在仓库根目录执行 `scripts/generate_tushare_interface_permissions_md.py`，会**同时**更新本 Markdown 与 **`docs/tushare-interface-permissions.json`**。")
    lines.append("- **机器检索**：自动化流程、脚本与 Agent **应优先读取 [`tushare-interface-permissions.json`](tushare-interface-permissions.json)**（结构化数组，按 `availability.code` / `apis` / `min_points_inferred` 筛选）；本表仅作人读对照。")
    lines.append("- **收录范围**：只包含 **叶子** `data.md`——即该文件所在目录下**没有子文件夹**的页面；含子目录的上级 `data.md`（专题总览）不列入本表，避免误当作独立接口。")
    lines.append("- **表格列**：`输出字段（官方文档表格）` 取自各页「输出参数」首张表的第一列字段名（若页面无表格或格式异常则为空）；`权限原文摘要` 为文首说明区截取，便于人工核对。")
    lines.append("- **积分门槛（解析）**：从说明文字中提取到的**最低**「××积分」要求（若同时出现试用档与高档，优先采用 ≥500 的最小档；个别页面如「基础积分」无数字时，`daily` 等按权限表归入 **120** 试用/免费档）。无法解析时为「—」，请回看该接口 `data.md` 或官网。")
    lines.append("- **单独购买参考价**：对官网标为单独计费的产品，按积分权限表中的定价填写；与具体 `pro.xxx` 的对应关系以官网为准。")
    lines.append("")
    lines.append("## 当前项目约定（个人账号）")
    lines.append("")
    lines.append(f"- **当前积分**：{USER_POINTS}。")
    lines.append("- **可调用范围（粗判）**：仅考虑「积分门槛」时，可调用文档解析门槛 **≤ 8000 积分** 的接口；**未单独购买**任何增值数据包时，凡标记为「单独权限」或表中单独定价的接口，**即使积分足够也不可依赖为已开通**。")
    lines.append("")
    lines.append("## 总表")
    lines.append("")
    lines.append("| doc_id | 分类 | 文档标题 | 接口 | 输出字段（官方文档表格） | 积分门槛（解析） | 单独购买参考价 | 8000积分且无单独订阅（粗判） | 权限原文摘要 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        apis_s = ",".join(r.apis) if r.apis else ("—" if not r.api_guess else str(r.api_guess))
        if not r.apis and r.api_guess:
            apis_s = str(r.api_guess)
        fields_s = ",".join(r.fields) if r.fields else "—"
        if len(fields_s) > 600:
            fields_s = fields_s[:600] + "…"

        pt = str(r.min_points) if r.min_points is not None else "—"
        sep = "—"
        if r.separate_sheet:
            sep = r.separate_sheet
        elif r.separate_doc:
            sep = "是（详见权限原文／官网单品）"

        blob = r.perm_blob.replace("\r", "")
        blob = " ".join(blob.split())
        if len(blob) > 220:
            blob = blob[:220] + "…"

        lines.append(
            "| "
            + " | ".join(
                (
                    cell_escape(r.doc_id),
                    cell_escape(r.crumb or "—"),
                    cell_escape(r.title_md),
                    cell_escape(apis_s),
                    cell_escape(fields_s),
                    cell_escape(pt),
                    cell_escape(sep),
                    cell_escape(availability(r)),
                    cell_escape(blob or "—"),
                )
            )
            + " |"
        )

    lines.append("")
    lines.append(f"<!-- generated: scripts/generate_tushare_interface_permissions_md.py md+json ns={gen_time} entries={len(rows)} -->")

    payload = {
        "_meta": {
            "schema_id": "zer0share.tushare_interface_permissions/v1",
            "user_points_reference": USER_POINTS,
            "leaf_docs_only": True,
            "availability_code_meaning": {
                "ok_points_gate_only": "在「仅凭积分、无单独购买 SKU」的默认假设下，解析出的积分门槛达标且未判为单独计费/依赖包",
                "insufficient_points": "解析出的积分门槛高于 user_points_reference",
                "needs_separate_addon": "判为需单独购买或未订阅的增值权限",
                "needs_parent_license_bundle": "依附其他付费条线（如港股日线、股票分钟等）才能使用",
                "unknown_points_gate": "正文中未解析到明确积分数字，需回看 data.md 或官网",
            },
        },
        "entries": [entry_json(r) for r in rows],
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT_MD, "and", OUT_JSON, "rows", len(rows))


if __name__ == "__main__":
    main()
