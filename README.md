# 酒店订单履约取证

节假日酒店订单履约取证系统的领域内核：以**只追加事件流**记录渠道报价快照、房型/设施承诺、
套餐拆分、合同版本、付款、退改规则、入住实况、商家与平台操作、差价申诉、调解结果与监管移交，
支持案件负责人从一条投诉还原「承诺 → 付款 → 履约 → 处置」完整链，并为公开页面输出最小化投影。

## 设计原则与落地位置

| 业务约束 | 落地方式 |
| --- | --- |
| 订单生效后价格变化不能改写原报价 | `QUOTE_FROZEN` 后报价快照只读；涨价只能追加 `PRICE_CHANGED`（`src/orders.py`） |
| 平台自动跟价与商家手工调价区分责任 | `change_type` 与 `actor` 强一致：`AUTO_MATCH/PLATFORM_AUTO` vs `MANUAL/MERCHANT`；`OrderState.liable_party()` 判定责任 |
| 房型降标、临住拒住、普通取消不混同 | `fulfillment_state` 三个互斥终态（`DOWNGRADED/REFUSED/CANCELLED`），只能登记一次并锁定；取消必须有 `cancel_reason`，降标/拒住禁止携带 |
| 截图/合同/照片校验来源并按敏感字段分级 | 必须带 `source` + `sha256:` 哈希；密级 = 材料头部分级与 `field_tags` 逐字段分级的最高者（`src/evidence.py`） |
| 消费者撤回未提交材料后停止公开 | 仅 `DRAFT` 可撤回；`SUBMITTED` 不可单方撤回 |
| 已进入投诉/执法卷宗的证据仍须保留 | `EVIDENCE_HELD` 后状态置 `HELD`，拒绝撤回/删除，版本历史继续保留 |
| 补充材料只能追加版本 | `EVIDENCE_RESUBMITTED` 的 `doc_version` 必须顺序递增，旧版本哈希不丢 |
| 批量导入与平台回执重复或乱序 | `ingest_batch`：按 `occurred_at` 重排分配 version；`event_id` 幂等；回执按 `(subject, source, raw_hash)` 指纹去重（`src/ingest.py`） |
| 从一条投诉还原全链 | `cases.build_case_view().chain()` 输出承诺/付款/履约/处置四段及统一时间线 |
| 公开页面最少个人信息 | `privacy.build_public_view()`：姓名/手机/证件脱敏，仅放行 `SUBMITTED + PUBLIC` 材料 |

## 事件信封

```json
{
  "event_id": "EV-011-MANUAL-MARKUP",
  "kind": "PRICE_CHANGED",
  "occurred_at": "2026-09-30T20:10:00+08:00",
  "subject_id": "O-20261001-1001",
  "version": 11,
  "payload": { "...": "逐 kind 的字段见 src/catalog.py 的 PAYLOAD_SPEC" }
}
```

- `version`：同一 `subject_id` 内的追加序号，从 1 递增；批量导入时由存储统一分配。
- `occurred_at`：业务发生时间（ISO-8601）。乱序到达合法，所有投影按其重排，不以入序定事实。
- `kind` 与载荷字段以 `src/catalog.py` 为准，信封 JSON 合同见 `contracts/event.schema.json`。

## 模块

- `src/catalog.py` — 事件目录、责任方、渠道、履约状态、证据密级/生命周期等枚举
- `src/contract.py` — 信封 + 载荷 + 枚举校验（`validate` / `validate_event` / `require_valid`）
- `src/store.py` — 只追加事件存储（幂等、顺序 version、业务时间读取）
- `src/ingest.py` — 批量导入（乱序重排、重复/回执去重、坏件隔离报告）
- `src/orders.py` — 订单履约聚合（报价冻结、跟价责任、状态分流、降标比对）
- `src/evidence.py` — 证据登记册（来源校验、分级、版本追加、撤回、留置）
- `src/cases.py` — 案件四段链与统一时间线
- `src/privacy.py` — PII 脱敏与公开页最小化投影

## 本地检查

```bash
python -m unittest discover -s tests   # 46 个用例
python -m src.demo                     # 从 fixtures/case.json 走完整链路
```

`fixtures/case.json` 是一个完整样本：平台报价 880 元冻结 → 平台自动跟价 860 →
节前商家手工加价到 1180 → 到店 5 星海景降为 3 星园景 → 差价申诉 → 部分调解 → 监管移交，
覆盖撤回草稿录音、聊天记录入卷留置等场景。
