"""Immutable, content-addressed multimodal extraction contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_BUNDLE = "document-bundle/v1"
SCHEMA_MANIFEST = "asset-manifest/v1"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE = {"password", "passwd", "token", "secret", "credential", "api_key", "apikey", "authorization", "cookie"}

def _security(value: Any, key: str = "") -> None:
    if key.lower().replace("-", "_") in _SENSITIVE:
        raise ValueError(f"sensitive field is forbidden: {key}")
    if isinstance(value, str):
        low = value.lower()
        if low.startswith(("http://", "https://", "ftp://")) or "@" in low and "://" in low:
            raise ValueError("URLs and credentials are forbidden")
        if ".." in value.replace("\\", "/").split("/"):
            raise ValueError("path traversal is forbidden")
    elif isinstance(value, Mapping):
        for k, v in value.items(): _security(v, str(k))
    elif isinstance(value, (list, tuple)):
        for v in value: _security(v, key)

def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict"): return value.to_dict()
    if isinstance(value, Mapping): return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_plain(v) for v in value]
    return value

def canonical_json(value: Any) -> str:
    """Canonical UTF-8 JSON: sorted keys, compact separators, no trailing newline."""
    _security(value)
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _hash(value: str, name: str = "sha256") -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value): raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value

def _freeze(value: Any) -> Any:
    if isinstance(value, dict): return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list): return tuple(_freeze(v) for v in value)
    return value

@dataclass(frozen=True)
class AssetRef:
    asset_id: str
    sha256: str
    def __post_init__(self):
        _hash(self.sha256);
        if self.asset_id != f"asset:sha256:{self.sha256}": raise ValueError("asset_id does not match sha256")
    @classmethod
    def from_bytes(cls, data: bytes) -> "AssetRef":
        digest = sha256_bytes(data); return cls(f"asset:sha256:{digest}", digest)
    def to_dict(self): return {"asset_id": self.asset_id, "sha256": self.sha256}

@dataclass(frozen=True)
class AssetEntry:
    asset_id: str
    kind: str
    sha256: str
    mime: str
    page: int | None = None
    parent_asset_id: str | None = None
    bbox_px: tuple[int, int, int, int] | None = None
    created_by: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    def __post_init__(self):
        AssetRef(self.asset_id, self.sha256)
        if not self.kind.strip() or not self.mime.strip(): raise ValueError("kind and mime are required")
        if self.page is not None and self.page < 1: raise ValueError("page must be positive")
        if self.parent_asset_id is not None and not self.parent_asset_id.startswith("asset:sha256:"): raise ValueError("invalid parent asset id")
        if self.bbox_px is not None and (len(self.bbox_px) != 4 or any(not isinstance(x, int) or x < 0 for x in self.bbox_px)): raise ValueError("invalid bbox_px")
        _security(self.created_by); _security(self.metadata)
        object.__setattr__(self, "bbox_px", tuple(self.bbox_px) if self.bbox_px else None)
        object.__setattr__(self, "created_by", MappingProxyType(dict(self.created_by)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
    @classmethod
    def from_bytes(cls, data: bytes, *, kind: str, mime: str, parent_asset_id: str | None = None, bbox_px=None, **kwargs):
        payload = data
        if parent_asset_id or bbox_px is not None:
            payload = canonical_json({"parent_asset_id": parent_asset_id, "bbox_px": bbox_px}).encode() + b"\n" + data
        digest = sha256_bytes(payload)
        return cls(f"asset:sha256:{digest}", kind, digest, mime, parent_asset_id=parent_asset_id, bbox_px=tuple(bbox_px) if bbox_px else None, **kwargs)
    def to_dict(self):
        d = {"asset_id": self.asset_id, "kind": self.kind, "page": self.page, "parent_asset_id": self.parent_asset_id, "bbox_px": list(self.bbox_px) if self.bbox_px else None, "sha256": self.sha256, "mime": self.mime, "created_by": dict(self.created_by)}
        if self.metadata: d["metadata"] = dict(self.metadata)
        return d

@dataclass(frozen=True)
class AssetManifest:
    bundle_id: str
    assets: tuple[AssetEntry, ...] = ()
    schema_version: str = SCHEMA_MANIFEST
    def __post_init__(self):
        if self.schema_version != SCHEMA_MANIFEST: raise ValueError("unsupported schema_version")
        if not self.bundle_id.startswith("sha256:"): raise ValueError("invalid bundle_id")
        object.__setattr__(self, "assets", tuple(self.assets))
        if len({a.asset_id for a in self.assets}) != len(self.assets): raise ValueError("duplicate asset_id")
    def to_dict(self): return {"schema_version": self.schema_version, "bundle_id": self.bundle_id, "assets": [a.to_dict() for a in self.assets]}
    @property
    def manifest_id(self): return "manifest:sha256:" + sha256_bytes(canonical_json(self).encode())
    def canonical_json(self): return canonical_json(self)
    def validate(self):
        for a in self.assets: AssetRef(a.asset_id, a.sha256)
        return True

@dataclass(frozen=True)
class DocumentBundle:
    document_id: str
    source_sha256: str
    page_count: int
    source: Mapping[str, Any]
    render: Mapping[str, Any]
    pages: tuple[Mapping[str, Any], ...] = ()
    asset_manifest_id: str = ""
    policy: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_BUNDLE
    def __post_init__(self):
        _hash(self.source_sha256, "source_sha256")
        if self.document_id != f"sha256:{self.source_sha256}": raise ValueError("document_id does not match source_sha256")
        if self.page_count < 0 or self.schema_version != SCHEMA_BUNDLE: raise ValueError("invalid bundle")
        _security(self.source); _security(self.render); _security(self.pages); _security(self.policy)
        object.__setattr__(self, "source", MappingProxyType(dict(self.source))); object.__setattr__(self, "render", MappingProxyType(dict(self.render))); object.__setattr__(self, "policy", MappingProxyType(dict(self.policy)))
        object.__setattr__(self, "pages", tuple(MappingProxyType(dict(p)) for p in self.pages))
    def to_dict(self): return {"schema_version": self.schema_version, "document_id": self.document_id, "source": dict(self.source), "source_sha256": self.source_sha256, "page_count": self.page_count, "render": dict(self.render), "pages": [dict(p) for p in self.pages], "asset_manifest_id": self.asset_manifest_id, "policy": dict(self.policy)}
    def canonical_json(self): return canonical_json(self)
    def validate(self):
        if sha256_bytes(self.source_sha256.encode()) == "": raise ValueError("invalid hash")
        return True
