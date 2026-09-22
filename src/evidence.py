"""证据材料生命周期与来源校验。

规则：
- 截图/合同/现场照片等必须登记来源（source）与内容哈希（raw_hash），哈希不符即来源存疑。
- 敏感字段分级：材料头部 sensitivity 与逐字段 field_tags 取最高级别。
- 补充材料只能以 EVIDENCE_RESUBMITTED 追加新版本，旧版本保留可溯。
- 消费者仅可撤回“未提交（DRAFT）”的材料；撤回即停止公开。
- 一经 EVIDENCE_HELD（进入投诉/执法卷宗）即留置，拒绝撤回与删除，版本追加照常保留。
"""
import hashlib
from dataclasses import dataclass, field

from . import catalog as c
from .errors import DomainError

_LEVEL_RANK = {
    c.SENSITIVITY_PUBLIC: 0,
    c.SENSITIVITY_INTERNAL: 1,
    c.SENSITIVITY_RESTRICTED: 2,
}


@dataclass
class EvidenceVersion:
    doc_version: int
    source: str
    raw_hash: str
    filename: str | None = None
    sensitivity: str = c.SENSITIVITY_PUBLIC
    field_tags: dict = field(default_factory=dict)


@dataclass
class EvidenceItem:
    evidence_ref: str
    evidence_type: str
    source: str
    raw_hash: str
    sensitivity: str
    field_tags: dict
    filename: str | None = None
    state: str = c.EV_DRAFT
    versions: list[EvidenceVersion] = field(default_factory=list)
    held_by: dict | None = None  # {"case_ref", "docket", "authority", "held_at"}
    withdrawn_reason: str | None = None

    def is_publicly_visible(self) -> bool:
        return self.state == c.EV_SUBMITTED and self.sensitivity == c.SENSITIVITY_PUBLIC


def verify_raw_hash(data: bytes, raw_hash: str) -> bool:
    """校验内容哈希，支持 sha256: 前缀；不支持的算法视为不通过。"""
    if not raw_hash:
        return False
    algo, _, expected = raw_hash.partition(":")
    if algo != "sha256" or not expected:
        return False
    return hashlib.sha256(data).hexdigest() == expected.lower()


def check_provenance(event: dict) -> list[str]:
    """来源校验：类型、来源、哈希协议缺一不可。"""
    p = event.get("payload", {})
    errors = []
    if not p.get("source"):
        errors.append("缺少来源 source")
    raw_hash = p.get("raw_hash", "")
    if not raw_hash.startswith("sha256:") or len(raw_hash) != 7 + 64:
        errors.append("raw_hash 必须为 sha256:<64位十六进制>")
    return errors


def effective_sensitivity(header: str, field_tags: dict) -> str:
    """材料有效密级 = 头部密级与所有字段密级的最高者。"""
    result = header
    for level in field_tags.values():
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK[result]:
            result = level
    return result


def build_registry(events: list[dict], *, raise_on_error: bool = True) -> dict[str, EvidenceItem]:
    """回放证据事件，建立证据登记册（可传入同一案件相关的多个事件流）。"""
    registry: dict[str, EvidenceItem] = {}

    def fail(msg):
        if raise_on_error:
            raise DomainError(msg)

    ordered = sorted(events, key=lambda e: (e["occurred_at"], e["version"]))
    for e in ordered:
        kind, p = e["kind"], e["payload"]

        if kind == c.KIND_EVIDENCE_UPLOADED:
            prov_errors = check_provenance(e)
            if prov_errors:
                fail(f"{p.get('evidence_id')}: " + "；".join(prov_errors))
                continue
            ref = p["evidence_id"]
            if ref in registry:
                fail(f"证据 {ref} 已登记，补充内容请走 EVIDENCE_RESUBMITTED 追加版本")
                continue
            header = p.get("sensitivity", c.SENSITIVITY_PUBLIC)
            tags = dict(p.get("field_tags", {}))
            bad = [v for v in tags.values() if v not in c.SENSITIVITY_LEVELS]
            if bad:
                fail(f"证据 {ref} 含未知敏感分级: {bad}")
                continue
            item = EvidenceItem(
                evidence_ref=ref,
                evidence_type=p["evidence_type"],
                source=p["source"],
                raw_hash=p["raw_hash"],
                sensitivity=effective_sensitivity(header, tags),
                field_tags=tags,
                filename=p.get("filename"),
                state=p.get("state", c.EV_DRAFT),
            )
            item.versions.append(EvidenceVersion(
                doc_version=1, source=p["source"], raw_hash=p["raw_hash"],
                filename=p.get("filename"), sensitivity=item.sensitivity, field_tags=tags,
            ))
            registry[ref] = item

        elif kind == c.KIND_EVIDENCE_RESUBMITTED:
            ref = p["evidence_ref"]
            item = registry.get(ref)
            if item is None:
                fail(f"补充版本所指证据 {ref} 不存在，新材料必须先 EVIDENCE_UPLOADED")
                continue
            if item.state == c.EV_WITHDRAWN:
                fail(f"证据 {ref} 已撤回，不能追加版本；如需重新提交请重新登记")
                continue
            next_version = max(v.doc_version for v in item.versions) + 1
            if p["doc_version"] != next_version:
                fail(f"证据 {ref} 下一版本必须为 {next_version}，收到 {p['doc_version']}（版本只追加）")
                continue
            tags = dict(p.get("field_tags", item.field_tags))
            header = p.get("sensitivity", item.sensitivity)
            new_level = effective_sensitivity(header, tags)
            item.versions.append(EvidenceVersion(
                doc_version=next_version, source=p["source"], raw_hash=p["raw_hash"],
                filename=p.get("filename"), sensitivity=new_level, field_tags=tags,
            ))
            item.source, item.raw_hash = p["source"], p["raw_hash"]
            item.sensitivity = new_level
            item.field_tags = tags

        elif kind == c.KIND_EVIDENCE_WITHDRAWN:
            ref = p["evidence_ref"]
            item = registry.get(ref)
            if item is None:
                fail(f"撤回失败：证据 {ref} 不存在")
                continue
            if item.state == c.EV_HELD:
                fail(f"证据 {ref} 已进入 {item.held_by['case_ref']} 卷宗，依法留置不得撤回")
                continue
            if item.state == c.EV_SUBMITTED:
                fail(f"证据 {ref} 已提交进入证据链，不能由消费者单方撤回")
                continue
            if item.state == c.EV_WITHDRAWN:
                continue  # 撤回操作幂等
            item.state = c.EV_WITHDRAWN
            item.withdrawn_reason = p.get("reason")

        elif kind == c.KIND_EVIDENCE_HELD:
            ref = p["evidence_ref"]
            item = registry.get(ref)
            if item is None:
                fail(f"留置失败：证据 {ref} 不存在")
                continue
            item.state = c.EV_HELD
            item.held_by = {
                "case_ref": p["case_ref"], "docket": p.get("docket"),
                "authority": p.get("authority"), "held_at": p["held_at"],
            }

    return registry
