#!/usr/bin/env python3
"""按更新登记簿修订治理会 PPTX：只替换有来源支持的文本，保留页面、对象名称和表格结构。"""
import argparse
import re
import zipfile

from openpyxl import load_workbook


def load_register(path):
    wb = load_workbook(path, data_only=True, read_only=True)

    def rows(name):
        data = list(wb[name].iter_rows(values_only=True))
        head = [str(h or "") for h in data[0]]
        return [dict(zip(head, r)) for r in data[1:] if any(c not in (None, "") for c in r)]

    readme = {str(r["字段"]): str(r["说明"]) for r in rows("00_阅读说明")}
    material_date = re.search(r"\d{4}-\d{2}-\d{2}", readme["资料口径日期"]).group(0)
    current = {
        r["事项编号"]: r
        for r in rows("里程碑更新")
        if r["材料范围"] == "本次治理会材料"
    }
    versions = {str(r["原始字段"]): str(r["PPT展示口径"]) for r in rows("版本与日期口径")}
    return material_date, versions["v1.8 当前"], current


def build_edits(rec, version):
    st = {k: v["当前口径/状态"] for k, v in rec.items()}
    dt = {k: v["日期展示建议"] for k, v in rec.items()}
    name = {k: v["事项名称"] for k, v in rec.items()}

    m101, m205, m310, m206 = "M-101", "M-205", "M-310", "M-206"
    dec, m407, risk = "DEC-044", "M-407", "RISK-118"
    risk_evidence, risk_review = st[risk].split("，")
    risk_evidence_text = f"{dt[risk]}提交降级证据"
    assert risk_evidence == risk_evidence_text, risk_evidence
    review_window = f"{dt[m206]}复盘"
    assert risk_review == review_window, risk_review
    signed = f"{dt[m101]}已完成"
    sampling = f"{dt[m205]}抽样复核"
    purchase_deadline = f"{dt[dec]}"
    before_purchase = "先于采购审定"
    frozen = st[m407]
    assert frozen.endswith(before_purchase)

    edits = {
        1: {
            "版本提示卡": {
                "当前页脚仍为 v1.7 草稿": f"当前治理包口径：{version}",
                "需按配套更新登记簿核对治理包口径": "资料口径：{MATERIAL_DATE}",
            },
            "本地材料提示": {
                "按配套更新登记簿更新文本、日期、状态与版号；保留模板、页脚对象和历史页结构。":
                    "已按配套更新登记簿同步文本、日期、状态与版号；保留模板、页脚对象和历史页结构。",
            },
        },
        2: {
            "目录_同步提醒": {
                "同步提醒：本稿中部分日期和状态仍沿用 6 月中旬工作稿，需用登记簿中本次治理会适用的口径替换。":
                    f"同步说明：已按登记簿同步本次治理会适用的日期、状态与版号（{version}，资料口径 {{MATERIAL_DATE}}）。",
            },
            "目录_范围说明": {
                "历史归档、模板样例、仅监控事项和后续版本草稿不应被当成本次治理会正文事实。":
                    "历史归档、模板样例、仅监控事项和后续版本草稿不作为本次治理会正文事实。",
            },
        },
        3: {
            "总览_标题": {"一页总览｜6 月治理包工作状态": f"一页总览｜{version}治理包工作状态"},
            "总览_状态芯片": {"黄色关注（待更新）": st[m206]},
            "总览_关键节点": {"合作点确认：仍待签": f"服务站签约：{signed}"},
            "总览_数据回收": {"口径草案待抽样": f"{dt[m205]}进入抽样复核"},
            "总览_决策项": {"服务包采购待确认": f"采购口径{purchase_deadline}确认"},
            "总览_事项表_旧稿": {
                "旧稿状态": "当前状态",
                "旧稿日期": "日期",
                "晨光中心合作点确认": name[m101],
                "待签署": st[m101],
                "6/20": dt[m101],
                "草案待抽样": st[m205],
                "6/26": dt[m205],
                "样本口径待冻结": frozen,
                "7/04": dt[m407],
                "志愿者培训排期": name[m310],
                "待排期": st[m310],
                "7月上旬": dt[m310],
                "未形成审定口径": f"{st[risk]}",
                "7/12前": dt[risk],
                "橙色风险": st[m206],
                "8月待定": dt[m206],
            },
            "总览_备注框": {
                "备注：本页是工作稿摘要，不是更新登记簿。请用配套 workbook 判断哪些口径适用于本次治理会。":
                    "备注：本页汇总本次治理会适用的状态与日期，登记簿原表不进入本页。",
            },
        },
        4: {
            "TL-合作点确认_标签": {"合作点确认": "服务站签约", "6/20 待确认": signed},
            "TL-数据口径_标签": {"数据采集口径": "数据回收口径", "6/26 草案": sampling},
            "TL-培训_标签": {"试点培训": "培训启动", "7月上旬待排期": f"{dt[m310]}已锁定"},
            "TL-回访_标签": {"首轮回访": "会后回访", "7/20": "回访准备中"},
            "TL-复盘_标签": {"季度复盘": "风险复盘", "8月待定": f"{dt[m206]}黄色关注"},
            "时间线_口径提醒": {
                "时间线页使用旧稿日期格式混杂：数字日期、自然周、月份待定并存。":
                    f"日期口径已统一为中文月日：抽样复核包冻结：{dt[m407]}{before_purchase}；{risk_evidence_text}。",
            },
        },
        5: {
            "工作流A_晨光卡": {
                "晨光中心 / 合作点确认": f"{name[m101]} / 合作点确认",
                "旧稿状态：待签署": f"当前状态：{st[m101]}",
                "旧稿日期：6/20": f"日期：{dt[m101]}",
                "备注：名称在旧稿中有多种写法": "备注：名称在旧稿中有多种写法，以登记簿正式写法为准",
            },
            "工作流A_培训卡": {
                "志愿者培训排期": name[m310],
                "旧稿状态：待排期": f"当前状态：{st[m310]}",
                "旧稿日期：7月上旬": f"启动日：{dt[m310]}",
                "备注：需看是否已有明确启动日": "备注：启动日与资源沟通页、决策页保持一致",
            },
            "工作流A_易混卡": {
                "历史材料页出现类似“站点确认”": "历史归档页保留原文，出现类似“站点确认”",
                "不自动并入当前合作点": "不并入当前晨光服务站签约",
            },
            "工作流A_行动清单": {
                "待核对口径": "当前口径",
                "是否改为已完成": "已完成，进入会后回访准备",
                "是否有启动日": f"启动日{dt[m310]}已锁定",
            },
        },
        6: {
            "工作流B_数据卡": {
                "旧稿：草案待抽样": f"当前：{st[m205]}",
                "影响：总览、时间线、风险说明": f"日期：{dt[m205]}；影响：总览、时间线、风险说明",
            },
            "工作流B_服务包卡": {
                "旧稿：待治理会确认": f"当前：{st[dec]}；决策期限：{dt[dec]}",
                "依赖：抽样复核包冻结后再审定": f"依赖 {m407} 样本冻结",
            },
            "工作流B_旧稿表": {
                "旧稿表述": "当前表述",
                "草案待抽样": st[m205],
                "可能已转入抽样复核": f"{dt[m205]}起进入抽样复核",
                "冻结口径待定": frozen,
                "样本冻结会影响采购审定": f"{dt[m407]}冻结，{m407} 是采购审定前置条件",
                "橙色风险": st[m206],
                "需确认是否仍为黄色关注": f"{review_window}，{risk_evidence_text}",
            },
        },
        7: {
            "决策风险_决策表": {
                "旧稿状态": "当前状态",
                "旧稿需确认内容": "确认内容",
                "是否按旧成本测算推进": f"{dt[dec]}审定采购口径",
                "与工作流B同步": f"依赖 {m407}，与工作流B同步",
                "冻结口径待定": "冻结口径已确认",
                "是否影响采购包审定": f"{dt[m407]}确认抽样复核包",
                "先于采购口径结论": f"先于采购口径审定（{m407}）",
                "7/20 首轮回访": "启动日已锁定",
                "是否受培训日期影响": f"培训启动日为{dt[m310]}",
                "橙色风险": st[m206],
                "是否仍需专项预案": f"{review_window}风险窗口",
                "与总览芯片同步": f"风险降级条件：{risk_evidence_text}",
            },
            "决策风险_口径提醒": {
                "请不要把后续版本草稿中的“试点二期扩展”写入本次治理会决策，除非登记簿明确列为本次范围。":
                    "“试点二期扩展”属后续版本草稿，不进入本次正文，除非登记簿明确列为本次范围。",
            },
        },
        8: {
            "资源沟通_节奏表": {
                "旧稿安排": "沟通安排",
                "签约后 3 个工作日": "签约完成后 3 个工作日",
                "合作点确认": name[m101],
                "可能需改为已完成后的通知节奏": f"{signed}，按完成后的通知节奏执行",
                "复核包冻结后通知": f"{dt[m407]}确认后通知",
                "抽样复核包": name[m407],
                "培训前一周": f"{dt[m310]}前一周",
                "培训排期": name[m310],
                "与启动日一致": "与启动日一致，培训启动日已锁定",
                "会前确认": f"{dt[dec]}确认",
                "仍需保留决策记录": f"{st[dec]}，仍需保留决策记录",
            },
            "资源沟通_注意框": {
                "本页多数为沟通节奏和模板性说明；仅在登记簿明确影响正文状态时才调整。":
                    f"涉及 {m101}/{m310}/{m407}/{dec}/{risk} 的沟通节奏按登记簿口径同步；"
                    f"风险降级条件：{risk_evidence_text}，{review_window}。其余说明仅在登记簿明确影响正文状态时才调整。",
            },
        },
        9: {
            "附录口径_版号": {
                "旧稿页脚：v1.7 草稿": f"当前页脚：{version}",
                "需与本次治理包版本一致": "与本次治理包版本一致",
            },
            "附录口径_日期": {
                "旧稿资料口径：2026-06-12": "资料口径：{MATERIAL_DATE}",
                "需核对登记簿生效日期": "已按登记簿资料口径日期同步",
            },
        },
    }
    return edits


SHAPE_RE = re.compile(r"<p:(sp|graphicFrame)>.*?</p:\1>", re.S)
NAME_RE = re.compile(r'<p:cNvPr id="\d+" name="([^"]*)"')


def edit_slide(xml, shape_edits, material_date, version):
    done = set()

    def sub_shape(m):
        block = m.group(0)
        name = NAME_RE.search(block).group(1)
        if name.startswith("页脚_版本口径_"):
            block = block.replace("v1.7 草稿", version).replace("2026-06-12", material_date)
            return block
        mapping = shape_edits.get(name)
        if not mapping:
            return block
        done.add(name)
        used = set()

        def sub_text(t):
            old = t.group(1)
            if old in mapping:
                used.add(old)
                return f"<a:t>{mapping[old].replace('{MATERIAL_DATE}', material_date)}</a:t>"
            return t.group(0)

        block = re.sub(r"<a:t>([^<]*)</a:t>", sub_text, block)
        missing = set(mapping) - used
        if missing:
            raise SystemExit(f"未找到待替换文本 {name}: {sorted(missing)}")
        return block

    xml = SHAPE_RE.sub(sub_shape, xml)
    missing = set(shape_edits) - done
    if missing:
        raise SystemExit(f"未找到对象 {sorted(missing)}")
    return xml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--register", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    material_date, version, rec = load_register(args.register)
    edits = build_edits(rec, version)

    with zipfile.ZipFile(args.deck) as zin, zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            m = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", info.filename)
            if m:
                num = int(m.group(1))
                xml = data.decode("utf-8")
                xml = edit_slide(xml, edits.get(num, {}), material_date, version)
                data = xml.encode("utf-8")
            zout.writestr(info, data)


if __name__ == "__main__":
    main()
