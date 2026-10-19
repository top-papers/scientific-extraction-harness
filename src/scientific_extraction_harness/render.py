"""Deterministic local artifact registration helpers.

This module deliberately treats rendered pages and extracted assets as opaque bytes;
it does not inspect or parse PDF/image formats.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest of *data*."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def asset_id(data: bytes, *, kind: str = "asset") -> str:
    return f"{kind}:{sha256_bytes(data)}"


def _check_bbox(bbox: Sequence[int | float]) -> tuple[int | float, int | float, int | float, int | float]:
    if len(bbox) != 4:
        raise ValueError("bbox must contain four coordinates")
    result = tuple(bbox)
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in result):
        raise ValueError("bbox coordinates must be numeric")
    if result[2] < result[0] or result[3] < result[1]:
        raise ValueError("bbox must have non-negative dimensions")
    return result  # type: ignore[return-value]


def crop_hash(parent_asset_id: str, pixel_bytes: bytes, bbox: Sequence[int | float]) -> str:
    """Hash crop identity, including its parent, coordinates, and bytes."""
    if not isinstance(parent_asset_id, str) or not parent_asset_id:
        raise ValueError("parent_asset_id is required")
    box = _check_bbox(bbox)
    payload = parent_asset_id.encode("utf-8") + b"\0" + canonical_json(list(box)) + b"\0" + pixel_bytes
    return sha256_bytes(payload)


def crop_metadata(parent_asset_id: str, pixel_bytes: bytes, bbox: Sequence[int | float], *, page: int | None = None, mime: str = "application/octet-stream") -> dict[str, Any]:
    box = _check_bbox(bbox)
    digest = crop_hash(parent_asset_id, pixel_bytes, box)
    result: dict[str, Any] = {"asset_id": f"crop:{digest}", "kind": "crop", "parent_asset_id": parent_asset_id, "bbox_px": list(box), "sha256": sha256_bytes(pixel_bytes), "crop_sha256": digest, "mime": mime}
    if page is not None:
        result["page"] = page
    return result


@dataclass(frozen=True)
class RegisteredAsset:
    asset_id: str
    kind: str
    sha256: str
    byte_length: int
    mime: str
    page: int | None = None
    parent_asset_id: str | None = None
    bbox_px: tuple[int | float, ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {"asset_id": self.asset_id, "kind": self.kind, "sha256": self.sha256, "byte_length": self.byte_length, "mime": self.mime}
        if self.page is not None: result["page"] = self.page
        if self.parent_asset_id is not None: result["parent_asset_id"] = self.parent_asset_id
        if self.bbox_px is not None: result["bbox_px"] = list(self.bbox_px)
        return result


def register_asset(data: bytes, *, kind: str = "asset", mime: str = "application/octet-stream", page: int | None = None, parent_asset_id: str | None = None, bbox_px: Sequence[int | float] | None = None) -> RegisteredAsset:
    digest = sha256_bytes(data)
    box = tuple(_check_bbox(bbox_px)) if bbox_px is not None else None
    identity = crop_hash(parent_asset_id, data, box) if parent_asset_id is not None and box is not None else digest
    return RegisteredAsset(f"{kind}:{identity}", kind, digest, len(data), mime, page, parent_asset_id, box)


def register_page(data: bytes, page: int, *, width: int | None = None, height: int | None = None, mime: str = "application/octet-stream") -> dict[str, Any]:
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("page must be a positive integer")
    if width is not None and (not isinstance(width, int) or width < 1): raise ValueError("width must be positive")
    if height is not None and (not isinstance(height, int) or height < 1): raise ValueError("height must be positive")
    result: dict[str, Any] = {"page": page, "asset_id": asset_id(data, kind="page"), "kind": "page", "sha256": sha256_bytes(data), "byte_length": len(data), "mime": mime}
    if width is not None: result["width"] = width
    if height is not None: result["height"] = height
    return result

# Explicit names useful to callers that want a function rather than a registry object.
page_metadata = register_page
