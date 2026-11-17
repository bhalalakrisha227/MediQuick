"""
Turns raw OCR lines into *candidate* medicine lines for the customer to review.

Pure Python, conservative on purpose: a line becomes a candidate only if it looks like a
medicine line (has a dosage form, strength, dose pattern or duration). Everything here is a
GUESS from noisy text. It is never a prescription decision.
All patterns use bounded quantifiers (no catastrophic backtracking) and inputs are length-capped.
"""
import re

MAX_LINES = 200
MAX_LINE_CHARS = 200
MAX_CANDIDATES = 40

FORMS = {"tab": "tablet", "tabs": "tablet", "tablet": "tablet", "tablets": "tablet",
         "cap": "capsule", "caps": "capsule", "capsule": "capsule", "capsules": "capsule",
         "syp": "syrup", "syrup": "syrup", "inj": "injection", "injection": "injection",
         "susp": "suspension", "suspension": "suspension", "drops": "drops", "oint": "ointment",
         "ointment": "ointment", "cream": "cream", "gel": "gel", "lotion": "lotion", "sachet": "sachet"}
_FORM_WORDS = "|".join(sorted(FORMS, key=len, reverse=True))
FORM_PREFIX = re.compile(rf"^(?:{_FORM_WORDS})\b\.?\s*", re.I)

STRENGTH = re.compile(r"(\d{1,4}(?:\.\d{1,3})?)\s{0,2}(mg|mcg|µg|μg|ug|g|ml|iu|%)(?![a-z])", re.I)
DOSE_PATTERN = re.compile(r"(?<![\d.])[0-3](?:\.5)?\s{0,2}-\s{0,2}[0-3](?:\.5)?\s{0,2}-\s{0,2}[0-3](?:\.5)?(?:\s{0,2}-\s{0,2}[0-3](?:\.5)?)?(?![\d.])")
DOSE_WORDS = re.compile(r"\b(?:od|bd|bid|tds|tid|qid|sos|hs|qhs|stat|once daily|twice daily|thrice daily|at night|bedtime|"
                        r"after (?:food|meals?)|before (?:food|meals?)|with food|empty stomach)\b", re.I)
DURATION = re.compile(r"(?:\bx|\bfor)?\s{0,2}(\d{1,3})\s{0,2}(days?|weeks?|wks?|months?)\b", re.I)
QUANTITY = re.compile(r"(?:\bqty|\bquantity|\bno\.?|#)\s{0,2}[:.]?\s{0,2}(\d{1,4})\b", re.I)

LEADING_JUNK = re.compile(r"^\s{0,10}(?:\d{1,2}\s{0,2}[.)]|[-•*>]|rx\b\.?|℞)\s{0,4}", re.I)
SKIP_LINE = re.compile(r"^\s{0,10}(?:dr\b|doctor|date|patient|name|age|sex|gender|address|reg|phone|mob|hospital|clinic|"
                       r"advice|follow|signature|sign\b|diagnosis|bp\b|weight|wt\b|ph\b|tel\b|rx\s*$)", re.I)


def normalise_unit(unit: str) -> str:
    unit = unit.lower()
    return "mcg" if unit in ("µg", "μg", "ug") else unit


def parse_strength(text: str):
    m = STRENGTH.search(text[:MAX_LINE_CHARS])
    if not m:
        return None
    value = float(m.group(1))
    unit = normalise_unit(m.group(2))
    shown = int(value) if value == int(value) else value
    return {"value": value, "unit": unit, "text": f"{shown} {unit}", "start": m.start()}


def _clean_name(raw: str) -> str:
    name = re.sub(r"[^A-Za-z0-9 \-]", " ", raw)
    name = re.sub(r"\s{2,}", " ", name).strip(" -")
    return name[:60]


def parse_line(text: str, confidence=None, index: int = 0):
    """Returns a candidate dict or None."""
    raw = (text or "").strip()[:MAX_LINE_CHARS]
    if len(raw) < 3 or SKIP_LINE.match(raw):
        return None
    body = LEADING_JUNK.sub("", raw)
    form = None
    m = FORM_PREFIX.match(body)
    if m:
        form = FORMS[m.group(0).strip(" .").lower()]
        body = body[m.end():]

    strength = parse_strength(body)
    dose = DOSE_PATTERN.search(body)
    words = DOSE_WORDS.findall(body)
    duration = DURATION.search(body)
    quantity = QUANTITY.search(body)

    if not (form or strength or dose or words or duration):
        return None

    cut = min([x.start() for x in (STRENGTH.search(body), DOSE_PATTERN.search(body), DOSE_WORDS.search(body),
                                   DURATION.search(body), QUANTITY.search(body)) if x] or [len(body)])
    name = _clean_name(body[:cut])
    if len(re.findall(r"[A-Za-z]", name)) < 3:
        return None

    dosage_parts = ([dose.group(0).replace(" ", "")] if dose else []) + [w.lower() for w in words]
    return {
        "line_index": index,
        "raw": raw,
        "name_guess": name,
        "form": form,
        "strength": {k: strength[k] for k in ("value", "unit", "text")} if strength else None,
        "dosage": " ".join(dosage_parts) or None,
        "duration": f"{duration.group(1)} {duration.group(2).lower()}" if duration else None,
        "quantity": int(quantity.group(1)) if quantity else None,
        "ocr_confidence": None if confidence is None else round(max(0.0, min(100.0, float(confidence))) / 100, 2),
    }


def parse_lines(lines) -> list:
    out = []
    for i, line in enumerate((lines or [])[:MAX_LINES]):
        if isinstance(line, dict):
            cand = parse_line(line.get("text", ""), line.get("confidence"), i)
        else:
            cand = parse_line(str(line), None, i)
        if cand:
            out.append(cand)
        if len(out) >= MAX_CANDIDATES:
            break
    return out
