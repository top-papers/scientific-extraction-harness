"""Deterministic local extraction adapters."""

from .base import AdapterDiagnostic, AdapterResult, ExtractionAdapter
from .figure import FigureAdapter
from .llm import LLMAdapter
from .ocr import OCRAdapter
from .table import TableAdapter

__all__ = [
    "AdapterDiagnostic",
    "AdapterResult",
    "ExtractionAdapter",
    "FigureAdapter",
    "LLMAdapter",
    "OCRAdapter",
    "TableAdapter",
]
