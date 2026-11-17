"""
Suggests catalogue products for a parsed candidate. SUGGESTIONS ONLY.

Nothing here selects, substitutes or approves a medicine: a strength mismatch is flagged and
caps the score, a different strength is never offered as "the same", and the customer and then
the pharmacist make every decision.
"""
import re
from difflib import SequenceMatcher

from .parser import parse_strength

MIN_SCORE = 0.6
HIGH_SCORE = 0.9
STRENGTH_MISMATCH_CAP = 0.7
MAX_SUGGESTIONS = 3
_STOP = {"tablet", "tablets", "capsule", "capsules", "syrup", "oral", "gel", "liquid", "sachet", "chewable", "drops",
         "injection", "cream", "ointment", "lotion", "mg", "mcg", "ml", "iu", "of", "and", "the", "strip", "pack", "bottle"}


def _tokens(text: str) -> list:
    return [t for t in re.findall(r"[a-z]{3,}", (text or "").lower()) if t not in _STOP]


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _best_name_score(guess_tokens: list, product: dict) -> float:
    pools = [_tokens(product.get("name", "")), _tokens(product.get("generic_name", "")), _tokens(product.get("brand", ""))]
    best = 0.0
    for pool in pools:
        for g in guess_tokens:
            for t in pool:
                best = max(best, _similar(g, t))
    return best


def strength_state(candidate_strength, product: dict):
    """True = same, False = different, None = cannot compare."""
    if not candidate_strength:
        return None
    ps = parse_strength(product.get("name", ""))
    if not ps:
        return None
    same = ps["unit"] == candidate_strength["unit"] and abs(ps["value"] - candidate_strength["value"]) < 1e-9
    return same


def suggest(candidate: dict, products) -> list:
    guess = _tokens(candidate.get("name_guess", ""))
    if not guess:
        return []
    out = []
    for p in products:
        if not p.get("is_active", True):
            continue
        score = _best_name_score(guess, p)
        if score < MIN_SCORE:
            continue
        state = strength_state(candidate.get("strength"), p)
        if state is False:
            score = min(score, STRENGTH_MISMATCH_CAP)
        confidence = "high" if (score >= HIGH_SCORE and state is not False) else ("medium" if score >= 0.75 else "low")
        out.append({"product_id": p["_id"], "name": p["name"], "score": round(score, 2),
                    "confidence": confidence, "strength_match": state,
                    "requires_prescription": bool(p.get("requires_prescription"))})
    out.sort(key=lambda s: (-s["score"], s["name"]))
    return out[:MAX_SUGGESTIONS]


def attach_suggestions(candidates, products) -> list:
    products = list(products)
    return [{**c, "suggestions": suggest(c, products)} for c in candidates]
