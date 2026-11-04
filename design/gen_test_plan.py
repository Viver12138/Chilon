"""Generate the mechanical part of the test plan from the design contracts.

Hand-written test design lives in the D6 volume; this script derives every case
that must exist by construction: one per legal transition, one per (aggregate,
state) rejection case, one per teacher action, one per endpoint, one per error
code, plus the fixed UI / metric / data-quality checkpoints.

Run after any contract change:
    python design/gen_test_plan.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
OUT = SCHEMAS / "test_plan.v1.json"

UI_CHECKS = [
    ("UI-01", "每屏最多一个主按钮"),
    ("UI-02", "按钮集合完全由 allowed_actions 决定"),
    ("UI-03", "四种通用状态（加载/空/错/冲突）均已实现"),
    ("UI-04", "冲突面板不允许静默覆盖"),
    ("UI-05", "学生视图从 AST 投影，非 CSS 隐藏"),
    ("UI-06", "问题条目可展开证据并跳转定位"),
    ("UI-07", "忽略 S1 必须填理由并留痕"),
    ("UI-08", "门禁过期时发布按钮禁用"),
    ("UI-09", "发布成功提示含版本号且声明不可修改"),
    ("UI-10", "预览与下载同源，预览先于下载"),
    ("UI-11", "断线重连后界面状态与接口一致"),
    ("UI-12", "outcome_unknown 时禁止重复提交并提示"),
]

METRICS = [
    ("M1", "引用可追溯率 100%"),
    ("M2", "来源定位可回读率 100%"),
    ("M3", "AI 内容误标率 0"),
    ("M4", "可判定节点验证覆盖率 ≥ 90%"),
    ("M5", "假通过数 0"),
    ("M6", "基准集通过率 ≥ 95%"),
    ("M7", "生成时长 P50 ≤ 4min / P95 ≤ 8min"),
    ("M8", "端到端时长 P50 ≤ 15min"),
    ("M9", "首轮 Plan 一次通过率 ≥ 70%"),
    ("M10", "教师编辑节点占比 ≤ 20%"),
    ("M11", "发布前重检轮次 ≤ 2"),
    ("M12", "S1 阻断密度 ≤ 1"),
    ("M13", "学生版泄漏数 0"),
    ("M14", "必需署名缺失数 0"),
    ("M15", "发布重复版本数 1"),
    ("M16", "未对账重试数 0"),
    ("M17", "SSE 事件丢失数 0"),
    ("M18", "并发 CAS 正确率 100%"),
]

DATA_CHECKS = [
    ("DATA-A1", "document_kind = mixed"),
    ("DATA-A2", "section 数量与 purpose 符合要求"),
    ("DATA-A3", "workbook_example ≥ 2 且绑定 workbook Citation"),
    ("DATA-A4", "gaokao_question ≥ 3 且绑定 gaokao_paper Citation"),
    ("DATA-A5", "ai_generated 题目 ≥ 2 且难度受控"),
    ("DATA-A6", "答案/解析/提示均非 student 可见"),
    ("DATA-A7", "选择题 options ≥ 2，answer_node_ids 指向后代"),
    ("DATA-A8", "节点 ID 全局唯一"),
    ("DATA-A9", "mock_question ≥ 1 且绑定 mock_exam Citation"),
    ("DATA-C1", "citation_id 唯一且至少被一个节点使用"),
    ("DATA-C2", "usage.rights 满足目标 Profile"),
    ("DATA-C3", "excerpt_hash = sha256(excerpt.text)"),
    ("DATA-C4", "locator 页码与类型匹配（含 segments）"),
    ("DATA-C5", "retrieval_run_id 指向真实检索"),
    ("DATA-G1", "Gate 结果为 passed/passed_with_warnings"),
    ("DATA-G2", "math_validation_result = validated"),
    ("DATA-G3", "检查目标 Revision 与发布 Revision 一致"),
    ("DATA-G4", "存在 S0 时发布被拒绝"),
    ("DATA-G5", "相同幂等键二次发布返回同一版本"),
    ("DATA-X1", "教师版含 student+teacher，不含 internal"),
    ("DATA-X2", "学生版答案类节点数 = 0"),
    ("DATA-X3", "学生版保留必需 Attribution"),
    ("DATA-X4", "两个导出文件 Hash 可复现"),
    ("DATA-X5", "export.source_document_hash 与版本一致"),
]


def load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def main() -> None:
    machines = load("state_machines.v1.json")
    actions = load("actions.v1.json")
    surface = load("api_surface.v1.json")
    nav = load("navigation.v1.json")

    # --- suite SM: legal transitions + per-state rejection -----------------
    sm_cases = []
    for agg in machines["aggregates"]:
        aid = agg["id"]
        for tr in agg["transitions"]:
            sm_cases.append(
                {
                    "id": f"SM-L-{aid}-{tr['id']}",
                    "kind": "legal",
                    "aggregate": aid,
                    "transition": tr["id"],
                    "from": tr["from"],
                    "to": tr["to"],
                    "expect": "ok",
                }
            )
        for state in agg["states"]:
            sm_cases.append(
                {
                    "id": f"SM-N-{aid}-{state}",
                    "kind": "reject",
                    "aggregate": aid,
                    "state": state,
                    "expect": "only_actions_whose_from_includes_state_succeed",
                }
            )

    # --- suite ACT: every teacher action, success + failure ----------------
    act_cases = []
    for agg in actions["aggregates"]:
        for act in agg["actions"]:
            if act["actor"] != "teacher":
                continue
            name = f"{agg['aggregate']}.{act['trigger']}"
            act_cases.append(
                {"id": f"ACT-OK-{name}", "action": name, "kind": "success", "expect": "state_advanced"}
            )
            act_cases.append(
                {"id": f"ACT-ERR-{name}", "action": name, "kind": "failure", "expect": "error_codes_listed"}
            )

    # --- suite API: every endpoint ---------------------------------------
    api_cases = []
    for ep in surface["action_endpoints"]:
        api_cases.append(
            {
                "id": f"API-ACT-{ep['name']}",
                "path": ep["path"],
                "method": ep["method"],
                "kind": "action",
                "checks": ["idempotency_replay", "state_version_conflict", "allowed_actions_present"],
            }
        )
    for res in surface["resources"]:
        slug = res["path"].strip("/").replace("/", "-").replace("{", "").replace("}", "")
        api_cases.append(
            {
                "id": f"API-RES-{res['method']}-{slug}",
                "path": res["path"],
                "method": res["method"],
                "kind": "resource",
                "checks": ["owner_isolation_404", "shape_matches_contract"],
            }
        )

    # --- suite ERR: every error code -------------------------------------
    err_cases = [
        {"id": f"ERR-{c['code']}", "code": c["code"], "http_status": c["http_status"]}
        for c in actions["error_codes"]
    ]

    # --- suite UI / METRIC / DATA ----------------------------------------
    ui_cases = [{"id": i, "assertion": t} for i, t in UI_CHECKS]
    metric_cases = [{"id": f"METRIC-{i}", "target": t} for i, t in METRICS]
    data_cases = [{"id": i, "assertion": t} for i, t in DATA_CHECKS]

    plan = {
        "schema": "chilon.test_plan",
        "schema_version": "1.0.0",
        "title": "Chilon 测试矩阵（机械派生部分）",
        "generated_by": "design/gen_test_plan.py",
        "note": "本文件由脚本生成，不要手改；改契约后重新生成。人工测试设计见 D6 分册。",
        "sources": {
            "state_machines": "schemas/state_machines.v1.json",
            "actions": "schemas/actions.v1.json",
            "api_surface": "schemas/api_surface.v1.json",
            "navigation": "schemas/navigation.v1.json",
        },
        "suites": [
            {
                "id": "SM",
                "name": "状态机迁移",
                "counts": {
                    "legal": sum(1 for c in sm_cases if c["kind"] == "legal"),
                    "reject": sum(1 for c in sm_cases if c["kind"] == "reject"),
                },
                "cases": sm_cases,
            },
            {"id": "ACT", "name": "教师动作", "count": len(act_cases), "cases": act_cases},
            {"id": "API", "name": "接口契约", "count": len(api_cases), "cases": api_cases},
            {"id": "ERR", "name": "错误码路径", "count": len(err_cases), "cases": err_cases},
            {"id": "UI", "name": "界面验收", "count": len(ui_cases), "cases": ui_cases},
            {"id": "METRIC", "name": "验收指标", "count": len(metric_cases), "cases": metric_cases},
            {"id": "DATA", "name": "数据质量与引用完整性", "count": len(data_cases), "cases": data_cases},
        ],
        "concurrency_checks": [
            {"id": "CC-01", "case": "两个请求同时审批同一 Plan，只有一个 CAS 成功"},
            {"id": "CC-02", "case": "两个请求同时暂停同一 Execution，只有一个生效"},
            {"id": "CC-03", "case": "两个 Draft 同时发布，后者进入 needs_rebase"},
            {"id": "CC-04", "case": "同一发布幂等键重复请求返回同一版本"},
            {"id": "CC-05", "case": "丢失 Lease 后用旧 Fencing Token 写入，不能推进状态"},
            {"id": "CC-06", "case": "outcome_unknown 分别对账为成功/失败/取消，不重复调用副作用工具"},
            {"id": "CC-07", "case": "SSE 断线按 Last-Event-ID 回放后，投影与数据库一致"},
            {"id": "CC-08", "case": "Draft 当前 Revision 与 Chat base_revision_no 不一致时返回冲突且不修改"},
            {"id": "CC-09", "case": "检查期间修改 Draft，旧报告变 stale 且发布门禁拒绝"},
            {"id": "CC-10", "case": "发布事务逐步注入失败，不产生孤立版本或重复消费审批"},
        ],
    }

    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total = sum(s.get("count", len(s["cases"])) for s in plan["suites"]) + len(plan["concurrency_checks"])
    print(f"test plan written: {OUT.name}")
    for s in plan["suites"]:
        print(f"  {s['id']:<7} {len(s['cases']):>4}")
    print(f"  {'CC':<7} {len(plan['concurrency_checks']):>4}")
    print(f"  total   {total:>4}")


if __name__ == "__main__":
    main()
