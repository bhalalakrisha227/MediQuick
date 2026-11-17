"""Tesseract engine via pytesseract. Needs the Tesseract program installed (see docs/PHASE5_PRESCRIPTIONS.md)."""
from ..errors import OcrError, OcrUnavailable
from .base import OcrEngine, OcrResult


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def __init__(self, cmd: str = "", lang: str = "eng", timeout: int = 60):
        self.cmd, self.lang, self.timeout = cmd or "", lang or "eng", timeout

    def _module(self):
        try:
            import pytesseract
        except ImportError as exc:
            raise OcrUnavailable("pytesseract is not installed.") from exc
        if self.cmd:
            pytesseract.pytesseract.tesseract_cmd = self.cmd
        return pytesseract

    def available(self) -> bool:
        try:
            self._module().get_tesseract_version()
            return True
        except OcrUnavailable:
            return False
        except Exception:
            return False

    def recognize(self, image) -> OcrResult:
        pt = self._module()
        try:
            data = pt.image_to_data(image, lang=self.lang, config="--oem 3 --psm 6",
                                    output_type=pt.Output.DICT, timeout=self.timeout)
        except pt.TesseractNotFoundError as exc:
            raise OcrUnavailable("The Tesseract program was not found.") from exc
        except RuntimeError as exc:                       # pytesseract raises RuntimeError on timeout
            raise OcrError("OCR timed out or failed.") from exc
        except Exception as exc:
            raise OcrError("OCR failed.") from exc
        return self._build(data)

    def _build(self, data) -> OcrResult:
        rows = {}
        for i, word in enumerate(data.get("text", [])):
            word = (word or "").strip()
            if not word:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            rows.setdefault(key, []).append((word, conf))
        lines = []
        for key in sorted(rows):
            words = rows[key]
            confs = [c for _, c in words if c >= 0]
            lines.append({"text": " ".join(w for w, _ in words),
                          "confidence": round(sum(confs) / len(confs), 1) if confs else None})
        return OcrResult(text="\n".join(l["text"] for l in lines), lines=lines, engine=self.name)
