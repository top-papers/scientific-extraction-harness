"""Structured, safe evidence locators with legacy string rendering."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping
from .bundles import _hash, _security

_MODALITIES = {"text", "table", "figure", "ocr", "chart"}
@dataclass(frozen=True)
class Locator:
    document_id: str
    page: int
    modality: str
    asset_id: str | None = None
    bbox_px: tuple[int, int, int, int] | None = None
    bbox_norm: tuple[float, float, float, float] | None = None
    char_start: int | None = None
    char_end: int | None = None
    table: Mapping[str, Any] | None = None
    figure: Mapping[str, Any] | None = None
    chart: Mapping[str, Any] | None = None
    def __post_init__(self):
        if not self.document_id.startswith("sha256:") or not _hash(self.document_id[7:], "document_id"): raise ValueError("invalid document_id")
        if self.page < 1 or self.modality not in _MODALITIES: raise ValueError("invalid page or modality")
        if self.asset_id is not None and not self.asset_id.startswith("asset:sha256:"): raise ValueError("invalid asset_id")
        if self.bbox_px is not None and (len(self.bbox_px) != 4 or any(not isinstance(x, int) or x < 0 for x in self.bbox_px)): raise ValueError("invalid bbox_px")
        if self.bbox_norm is not None and (len(self.bbox_norm) != 4 or any(not 0 <= x <= 1 for x in self.bbox_norm)): raise ValueError("invalid bbox_norm")
        if self.char_start is not None and (self.char_start < 0 or self.char_end is None or self.char_end < self.char_start): raise ValueError("invalid character range")
        _security(self.table); _security(self.figure); _security(self.chart)
        object.__setattr__(self, "bbox_px", tuple(self.bbox_px) if self.bbox_px else None)
        object.__setattr__(self, "bbox_norm", tuple(self.bbox_norm) if self.bbox_norm else None)
    def to_dict(self):
        d = {"document_id":self.document_id,"page":self.page,"modality":self.modality,"asset_id":self.asset_id,"bbox_px":list(self.bbox_px) if self.bbox_px else None,"bbox_norm":list(self.bbox_norm) if self.bbox_norm else None,"char_start":self.char_start,"char_end":self.char_end,"table":self.table,"figure":self.figure,"chart":self.chart}
        return {k:v for k,v in d.items() if v is not None}
    def render(self) -> str:
        parts = [f"page:{self.page}"]
        if self.modality == "text":
            if self.char_start is not None: parts.append(f"chars:{self.char_start}-{self.char_end}")
        elif self.modality == "table" and self.table:
            parts += [f"table:{self.table.get('id','')}" ]
            if self.table.get("row") is not None: parts.append(f"row:{self.table['row']}")
            if self.table.get("column") is not None: parts.append(f"column:{self.table['column']}")
            if self.table.get("cell") is not None: parts.append(f"cell:{self.table['cell']}")
        elif self.modality == "figure" and self.figure:
            parts += [f"figure:{self.figure.get('id','')}" ]
            if self.figure.get("panel") is not None: parts.append(f"panel:{self.figure['panel']}")
            if self.figure.get("series") is not None: parts.append(f"series:{self.figure['series']}")
        elif self.modality == "chart" and self.chart:
            if self.chart.get("x") is not None: parts.append(f"x:{self.chart['x']}")
            if self.chart.get("y") is not None: parts.append(f"y:{self.chart['y']}")
        else: parts.append(self.modality)
        return "/".join(str(p) for p in parts)
    @property
    def locator(self): return self.render()
