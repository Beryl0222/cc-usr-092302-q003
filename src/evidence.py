"""证据卷：截图、合同、现场照片等材料的来源校验与生命周期管理。

规则：
- 来源校验：每份材料登记来源方式与内容哈希，可重新计算哈希核验未被替换；
- 敏感分级：PUBLIC / PROTECTED / CONFIDENTIAL，公开视图按级别脱敏或隐藏；
- 版本只追加：补充材料产生新版本，旧版本哈希保留，历史不可改写；
- 撤回：未进入卷宗的材料可撤回，撤回后停止公开；已进入投诉或执法卷宗
  （DOCKETED）的材料适用法定留存，拒绝撤回，且任何状态下都不得删除。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain import DomainError, sha256_text


@dataclass(frozen=True)
class MaterialVersion:
    version: int
    hash: str
    occurred_at: str


@dataclass
class Material:
    material_id: str
    material_type: str
    title: str
    sensitivity: str
    origin: dict
    submitted: bool
    state: str = "DRAFT"  # DRAFT / SUBMITTED / WITHDRAWN / DOCKETED
    versions: list[MaterialVersion] = field(default_factory=list)
    docket_id: str | None = None

    @property
    def latest(self) -> MaterialVersion:
        return self.versions[-1]

    @property
    def retained(self) -> bool:
        """进入卷宗的材料必须保留（法定留存）。"""
        return self.state == "DOCKETED"


class EvidenceVault:
    def __init__(self) -> None:
        self._materials: dict[str, Material] = {}

    # ------------------------------------------------------------------
    # 事件应用
    # ------------------------------------------------------------------

    def apply(self, event: dict) -> None:
        kind = event["kind"]
        payload = event.get("payload", {})
        handler = getattr(self, f"_on_{kind.lower()}", None)
        if handler is not None:
            handler(event["subject_id"], payload, event)

    def _on_evidence_registered(self, material_id: str, payload: dict, event: dict) -> None:
        if material_id in self._materials:
            raise DomainError(f"材料 {material_id} 已登记，不能重复注册")
        material = Material(
            material_id=material_id,
            material_type=payload["material_type"],
            title=payload["title"],
            sensitivity=payload["sensitivity"],
            origin=dict(payload["origin"]),
            submitted=bool(payload["submitted"]),
            state="SUBMITTED" if payload["submitted"] else "DRAFT",
        )
        material.versions.append(MaterialVersion(1, payload["hash"], event["occurred_at"]))
        self._materials[material_id] = material

    def _on_evidence_version_added(self, material_id: str, payload: dict, event: dict) -> None:
        material = self._require(material_id)
        if material.state in ("WITHDRAWN", "DOCKETED"):
            raise DomainError(f"材料 {material_id} 处于 {material.state}，不能再追加版本")
        # 只追加：版本号递增，旧版本保留
        material.versions.append(
            MaterialVersion(material.latest.version + 1, payload["hash"], event["occurred_at"])
        )

    def _on_evidence_submitted(self, material_id: str, payload: dict, event: dict) -> None:
        material = self._require(material_id)
        if material.state != "DRAFT":
            raise DomainError(f"材料 {material_id} 当前状态 {material.state}，不能提交")
        material.state = "SUBMITTED"
        material.submitted = True

    def _on_evidence_withdrawn(self, material_id: str, payload: dict, event: dict) -> None:
        material = self._require(material_id)
        if material.state == "DOCKETED":
            raise DomainError(f"材料 {material_id} 已进入卷宗 {material.docket_id}，依法留存，拒绝撤回")
        if material.state == "WITHDRAWN":
            raise DomainError(f"材料 {material_id} 已撤回")
        # 撤回后停止公开；记录保留在卷内供承办人审计
        material.state = "WITHDRAWN"

    def _on_evidence_docketed(self, material_id: str, payload: dict, event: dict) -> None:
        material = self._require(material_id)
        if material.state == "DOCKETED":
            if material.docket_id != payload["docket_id"]:
                raise DomainError(f"材料 {material_id} 已进入卷宗 {material.docket_id}，不能重复入卷")
            return
        material.state = "DOCKETED"
        material.docket_id = payload["docket_id"]

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, material_id: str) -> Material:
        return self._require(material_id)

    def verify_origin(self, material_id: str, content: str, version: int | None = None) -> bool:
        """来源校验：重新计算内容哈希，与登记版本比对（默认最新版本）。"""
        material = self._require(material_id)
        digest = sha256_text(content)
        if version is None:
            return material.latest.hash == digest
        return any(v.version == version and v.hash == digest for v in material.versions)

    def public_metadata(self) -> list[dict]:
        """公开页面可见的材料元数据：撤回材料不展示，来源细节按敏感度隐藏。"""
        result = []
        for material in self._materials.values():
            if material.state == "WITHDRAWN":
                continue  # 撤回后停止公开
            entry = {
                "material_id": material.material_id,
                "material_type": material.material_type,
                "title": material.title,
                "version": material.latest.version,
                "verified": True,
            }
            if material.sensitivity == "PUBLIC":
                entry["origin_method"] = material.origin.get("method")
                entry["captured_at"] = material.origin.get("captured_at")
            # PROTECTED / CONFIDENTIAL：来源账号、设备等细节不公开
            result.append(entry)
        return sorted(result, key=lambda e: e["material_id"])

    def handler_metadata(self) -> list[dict]:
        """承办人视图：包含撤回材料（带状态标记）与完整来源信息。"""
        return [
            {
                "material_id": m.material_id,
                "material_type": m.material_type,
                "title": m.title,
                "sensitivity": m.sensitivity,
                "state": m.state,
                "docket_id": m.docket_id,
                "versions": [{"version": v.version, "hash": v.hash} for v in m.versions],
                "origin": dict(m.origin),
            }
            for m in sorted(self._materials.values(), key=lambda m: m.material_id)
        ]

    # ------------------------------------------------------------------

    def _require(self, material_id: str) -> Material:
        try:
            return self._materials[material_id]
        except KeyError:
            raise DomainError(f"材料 {material_id} 不存在") from None
