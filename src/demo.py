"""端到端演示：批量导入（乱序/去重）→ 还原案件链 → 输出公开投影。

运行：python -m src.demo
"""
import json
import random
from pathlib import Path

from .cases import build_case_view
from .ingest import ingest_batch
from .privacy import build_public_view
from .store import EventStore


def main() -> None:
    data = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "case.json").read_text(encoding="utf-8")
    )
    store = EventStore()
    batch = data["order_events"] + data["evidence_events"] + data["case_events"]
    random.Random(7).shuffle(batch)  # 模拟平台回执/批量导入乱序

    report = ingest_batch(store, batch)
    print(f"导入：接受 {len(report.accepted)}，重复 {len(report.duplicates)}，"
          f"拒收 {len(report.rejected)}")

    case = build_case_view(
        store.stream(data["case_ref"]),
        store.stream(data["order_subject_id"]),
        store.stream(data["order_subject_id"]),
    )
    chain = case.chain()

    print("\n[承诺] 冻结报价：",
          chain["commitment"]["frozen_quote_ref"],
          "房型：", chain["commitment"]["promises"][-1]["room_type"],
          chain["commitment"]["promises"][-1]["star_class"], "星")
    print("[付款] 付款笔数：", len(chain["payment"]["payments"]),
          "退款：", [(r["amount"], r["reason"]) for r in chain["payment"]["refunds"]])
    print("[履约] 状态：", chain["fulfillment"]["state"],
          "责任方：", chain["fulfillment"]["liable_party"])
    print("       价格轨迹：",
          [(p["change_type"], p["actor"], p["old"], p["new"])
           for p in chain["fulfillment"]["price_changes"]])
    print("       降标项：", [g["field"] for g in chain["fulfillment"]["downgrade_gaps"]])
    print("[处置] 申诉：", chain["disposition"]["appeal"]["appeal_ref"],
          "调解：", [m["outcome"] for m in chain["disposition"]["mediations"]],
          "移交：", chain["disposition"]["referral"]["docket"])
    print("       留置证据：", case.held_dockets())

    pub = build_public_view(case, data["consumer_pii"])
    print("\n[公开页] 消费者：", pub.consumer,
          "\n         公开材料：", [e["evidence_ref"] for e in pub.public_evidence],
          " 隐去材料数：", pub.withheld_count)


if __name__ == "__main__":
    main()
