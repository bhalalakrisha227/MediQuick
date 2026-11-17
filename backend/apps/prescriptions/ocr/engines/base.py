from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OcrResult:
    text: str
    lines: list = field(default_factory=list)     # [{"text": str, "confidence": float | None}]  confidence 0-100
    engine: str = ""


class OcrEngine(ABC):
    """Interface every OCR engine implements, so PaddleOCR can be added later as another class."""
    name = "base"

    @abstractmethod
    def available(self) -> bool:
        """True if this engine can run on this machine."""

    @abstractmethod
    def recognize(self, image) -> OcrResult:
        """image: preprocessed numpy array. Raises OcrUnavailable / OcrError."""
