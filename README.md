# 酒店订单履约取证

面向节假日酒店预订纠纷的订单履约取证系统：以只追加事件流记录渠道报价快照、
房型与设施承诺、套餐拆分、合同版本、付款、退改规则、入住实况、商家与平台
操作、差价申诉、调解结果及监管移交，承办人可从一条投诉还原
「承诺 → 付款 → 履约 → 处置」完整证据链。

## 架构

```
contracts/event.schema.json   事件信封合同（跨系统共享）
src/contract.py               信封与 payload 校验（权威定义）
src/domain.py                 枚举、异常与脱敏工具
src/event_store.py            只追加事件存储：幂等去重、乱序回放、批量导入回执
src/order.py                  订单投影：冻结报价、调价责任、履约状态机
src/evidence.py               证据卷：来源校验、敏感分级、版本追加、撤回与留存
src/case.py                   案件链：投诉还原全链路，公开视图最小化个人信息
fixtures/scenario.json        完整业务场景（国庆预订纠纷全流程）
```

## 关键不变量

- **报价不可改写**：订单生效（`PLAN_FROZEN`）后冻结报价固定；价格变化只能以
  `PRICE_CHANGED` 追加，且区分平台自动跟价（`PLATFORM_AUTO`）与商家手工调价
  （`MERCHANT_MANUAL`）以明确责任。
- **状态不混用**：房型降标（`ROOM_DOWNGRADE`）、临时拒住（`STAY_REFUSAL`）、
  普通取消（`CANCELLED`）互斥；拒住后的强制取消（`FORCE_CANCELLED`）沿用
  拒住责任链，不记为普通取消。
- **证据法定留存**：未提交材料可撤回并停止公开；已进入投诉或执法卷宗
  （`DOCKETED`）的材料拒绝撤回，任何状态都不得删除。
- **版本只追加**：补充材料、合同与退改规则只能递增版本，历史哈希保留可核验。
- **导入幂等**：重复 `event_id` 内容一致则忽略，不一致则冲突报错；
  回放按 `occurred_at` 排序，与写入先后无关。
- **公开最小化**：公开页面只展示维权所需信息——化名脱敏、编号打码、
  撤回与 CONFIDENTIAL 材料不出现。

## 本地检查

```bash
python3 -m unittest discover -s tests
```
