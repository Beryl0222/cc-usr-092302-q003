"""事件目录：渠道报价、承诺、合同、付款、履约、处置各环节允许登记的事件。

事件按主题（subject_id）追加。同一主题内 version 从 1 递增、只增不改；
occurred_at 表示业务发生时间，导入乱序时以其重排，不以入序决定事实。
"""

# --- 责任方：平台自动跟价与商家手工调价必须可区分 ---
ACTOR_PLATFORM_AUTO = "PLATFORM_AUTO"      # 平台系统自动跟价
ACTOR_MERCHANT = "MERCHANT"                 # 商家（含商家手工调价）
ACTOR_PLATFORM_STAFF = "PLATFORM_STAFF"     # 平台人工操作
ACTOR_CONSUMER = "CONSUMER"
ACTOR_REGULATOR = "REGULATOR"
ACTOR_MEDIATOR = "MEDIATOR"
PRICE_ACTORS = (ACTOR_PLATFORM_AUTO, ACTOR_MERCHANT)
ALL_ACTORS = (
    ACTOR_PLATFORM_AUTO,
    ACTOR_MERCHANT,
    ACTOR_PLATFORM_STAFF,
    ACTOR_CONSUMER,
    ACTOR_REGULATOR,
    ACTOR_MEDIATOR,
)

# --- 渠道 ---
CHANNEL_PLATFORM = "PLATFORM"        # 平台自有页面
CHANNEL_MERCHANT_DIRECT = "DIRECT"   # 商家直营
CHANNEL_OTA_A = "OTA_A"
CHANNEL_OTA_B = "OTA_B"
CHANNEL_OFFLINE = "OFFLINE"          # 线下门店/电话
ALL_CHANNELS = (
    CHANNEL_PLATFORM,
    CHANNEL_MERCHANT_DIRECT,
    CHANNEL_OTA_A,
    CHANNEL_OTA_B,
    CHANNEL_OFFLINE,
)

# --- 价格变动类型 ---
PRICE_CHANGE_AUTO_MATCH = "AUTO_MATCH"   # 平台自动跟价：责任在平台侧
PRICE_CHANGE_MANUAL = "MANUAL"           # 商家手工调价
PRICE_CHANGE_TYPES = (PRICE_CHANGE_AUTO_MATCH, PRICE_CHANGE_MANUAL)

# --- 履约状态：降标 / 临住拒住 / 普通取消不得混成同一状态 ---
FULFILLMENT_NORMAL = "NORMAL"                 # 按约履行
FULFILLMENT_DOWNGRADED = "DOWNGRADED"         # 房型/星级降标
FULFILLMENT_REFUSED_AT_CHECKIN = "REFUSED"    # 临近入住毁约拒住
FULFILLMENT_CANCELLED = "CANCELLED"           # 普通取消
FULFILLMENT_STATES = (
    FULFILLMENT_NORMAL,
    FULFILLMENT_DOWNGRADED,
    FULFILLMENT_REFUSED_AT_CHECKIN,
    FULFILLMENT_CANCELLED,
)

# --- 取消责任归因（普通取消内部再区分，仍与降标/拒住互斥） ---
CANCEL_CONSUMER = "BY_CONSUMER"
CANCEL_MERCHANT = "BY_MERCHANT"
CANCEL_FORCE_MAJEURE = "FORCE_MAJEURE"
CANCEL_REASONS = (CANCEL_CONSUMER, CANCEL_MERCHANT, CANCEL_FORCE_MAJEURE)

# --- 证据材料类型 ---
EV_SCREENSHOT = "SCREENSHOT"
EV_CONTRACT = "CONTRACT"
EV_PHOTO = "PHOTO"
EV_CHAT_LOG = "CHAT_LOG"
EV_RECEIPT = "RECEIPT"             # 平台/渠道回执
EV_AUDIO = "AUDIO"
EV_OTHER = "OTHER"
EVIDENCE_TYPES = (
    EV_SCREENSHOT,
    EV_CONTRACT,
    EV_PHOTO,
    EV_CHAT_LOG,
    EV_RECEIPT,
    EV_AUDIO,
    EV_OTHER,
)

# --- 敏感字段分级 ---
SENSITIVITY_PUBLIC = "PUBLIC"        # 可公开展示
SENSITIVITY_INTERNAL = "INTERNAL"    # 仅办案/平台内部
SENSITIVITY_RESTRICTED = "RESTRICTED"  # 身份证、联系方式等高敏
SENSITIVITY_LEVELS = (SENSITIVITY_PUBLIC, SENSITIVITY_INTERNAL, SENSITIVITY_RESTRICTED)

# --- 证据生命周期 ---
EV_DRAFT = "DRAFT"                 # 未提交：消费者可撤回，撤回即停止公开
EV_SUBMITTED = "SUBMITTED"         # 已提交，进入订单证据链
EV_WITHDRAWN = "WITHDRAWN"         # 提交前撤回（仅 DRAFT 可撤回）
EV_HELD = "HELD"                   # 已被卷宗留置：不得删除/公开撤回
EVIDENCE_STATES = (EV_DRAFT, EV_SUBMITTED, EV_WITHDRAWN, EV_HELD)

# --- 案件/处置状态 ---
CASE_OPENED = "OPENED"
CASE_ESCALATED = "ESCALATED"
CASE_MEDIATING = "MEDIATING"
CASE_MEDIATED = "MEDIATED"
CASE_REFERRED = "REFERRED"         # 移交监管/执法
CASE_CLOSED = "CLOSED"
CASE_STATES = (
    CASE_OPENED,
    CASE_ESCALATED,
    CASE_MEDIATING,
    CASE_MEDIATED,
    CASE_REFERRED,
    CASE_CLOSED,
)

# --- 事件目录：kind -> (必需载荷字段, 选填载荷字段) ---
# 报价与价格
KIND_QUOTE_CAPTURED = "QUOTE_CAPTURED"                 # 渠道报价快照登记
KIND_QUOTE_FROZEN = "QUOTE_FROZEN"                     # 订单生效，报价冻结
KIND_PRICE_CHANGED = "PRICE_CHANGED"                   # 生效后价格变动（不改原报价）
# 承诺
KIND_ROOM_PROMISED = "ROOM_PROMISED"                   # 房型/星级/设施承诺
KIND_PACKAGE_SPLIT = "PACKAGE_SPLIT"                   # 套餐拆分
KIND_CONTRACT_VERSION = "CONTRACT_VERSION"             # 合同版本（追加）
# 付款 / 退改
KIND_PAYMENT = "PAYMENT"
KIND_PAYMENT_REFUND = "PAYMENT_REFUND"
KIND_CANCELLATION_POLICY = "CANCELLATION_POLICY"       # 退改规则版本
# 入住实况
KIND_CHECKIN_REPORTED = "CHECKIN_REPORTED"             # 入住实况登记（状态分流）
# 商家与平台操作
KIND_MERCHANT_ACTION = "MERCHANT_ACTION"
KIND_PLATFORM_ACTION = "PLATFORM_ACTION"
# 证据
KIND_EVIDENCE_UPLOADED = "EVIDENCE_UPLOADED"
KIND_EVIDENCE_RESUBMITTED = "EVIDENCE_RESUBMITTED"     # 补充材料：仅追加新版本
KIND_EVIDENCE_WITHDRAWN = "EVIDENCE_WITHDRAWN"         # 未提交材料撤回
KIND_EVIDENCE_HELD = "EVIDENCE_HELD"                   # 进入投诉/执法卷宗，留置
# 差价申诉与处置
KIND_PRICE_APPEAL = "PRICE_APPEAL"                     # 差价申诉
KIND_CASE_OPENED = "CASE_OPENED"
KIND_CASE_MEDIATION = "CASE_MEDIATION"                 # 调解过程/结果
KIND_CASE_REFERRAL = "CASE_REFERRAL"                   # 监管移交
KIND_CASE_CLOSED = "CASE_CLOSED"

PAYLOAD_SPEC = {
    KIND_QUOTE_CAPTURED: (
        ["channel", "room_type", "price_amount", "currency", "captured_at"],
        ["quote_ref", "facilities", "source_evidence_id", "raw_hash"],
    ),
    KIND_QUOTE_FROZEN: (
        ["quote_ref"],
        ["order_ref"],
    ),
    KIND_PRICE_CHANGED: (
        ["quote_ref", "new_price_amount", "change_type", "actor"],
        ["old_price_amount", "reason", "receipt_evidence_id"],
    ),
    KIND_ROOM_PROMISED: (
        ["room_type", "star_class", "facilities"],
        ["promise_ref", "source_evidence_id"],
    ),
    KIND_PACKAGE_SPLIT: (
        ["package_ref", "components"],
        ["parent_package_ref"],
    ),
    KIND_CONTRACT_VERSION: (
        ["contract_ref", "doc_version", "terms"],
        ["source_evidence_id", "supersedes_doc_version"],
    ),
    KIND_PAYMENT: (
        ["amount", "currency", "paid_at"],
        ["method", "receipt_evidence_id"],
    ),
    KIND_PAYMENT_REFUND: (
        ["amount", "currency", "refunded_at"],
        ["method", "reason"],
    ),
    KIND_CANCELLATION_POLICY: (
        ["policy_version", "rules"],
        ["effective_at"],
    ),
    KIND_CHECKIN_REPORTED: (
        ["reported_at", "fulfillment_state"],
        ["actual_room_type", "actual_star_class", "actual_facilities",
         "cancel_reason", "note", "evidence_id"],
    ),
    KIND_MERCHANT_ACTION: (
        ["action", "acted_at"],
        ["note", "evidence_id"],
    ),
    KIND_PLATFORM_ACTION: (
        ["action", "acted_at", "actor"],
        ["note", "evidence_id"],
    ),
    KIND_EVIDENCE_UPLOADED: (
        ["evidence_id", "evidence_type", "source", "raw_hash", "sensitivity"],
        ["filename", "media_uri", "field_tags", "state"],
    ),
    KIND_EVIDENCE_RESUBMITTED: (
        ["evidence_ref", "doc_version", "source", "raw_hash"],
        ["filename", "media_uri", "field_tags", "sensitivity", "note"],
    ),
    KIND_EVIDENCE_WITHDRAWN: (
        ["evidence_ref"],
        ["reason"],
    ),
    KIND_EVIDENCE_HELD: (
        ["evidence_ref", "case_ref", "held_at"],
        ["docket", "authority"],
    ),
    KIND_PRICE_APPEAL: (
        ["appeal_ref", "quote_ref", "expected_amount", "claimed_amount"],
        ["reason", "opened_at"],
    ),
    KIND_CASE_OPENED: (
        ["case_ref", "opened_at"],
        ["appeal_ref", "order_subject_id", "summary"],
    ),
    KIND_CASE_MEDIATION: (
        ["case_ref", "mediated_at", "outcome"],
        ["award_amount", "currency", "note"],
    ),
    KIND_CASE_REFERRAL: (
        ["case_ref", "referred_at", "authority"],
        ["docket", "reason"],
    ),
    KIND_CASE_CLOSED: (
        ["case_ref", "closed_at", "resolution"],
        ["note"],
    ),
}

ALL_KINDS = tuple(PAYLOAD_SPEC.keys())
