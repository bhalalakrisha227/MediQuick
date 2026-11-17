"""
Product classification rules.

IMPORTANT: these are conservative engineering defaults, NOT verified legal
rules. What may be sold online, and under which conditions, must be confirmed
with a qualified Indian pharmacy/healthcare lawyer (see docs/COMPLIANCE_CHECKLIST.md)
before any real sale. Change them here in one place if the advice differs.
"""
OTC = "OTC"
SCHEDULES = (OTC, "H", "H1", "X")

# Anything that is not OTC requires a verified prescription in this system.
# Schedule X is blocked from online ordering entirely until legal review says otherwise.
BLOCKED_ONLINE_SCHEDULES = frozenset({"X"})


def requires_prescription(schedule: str) -> bool:
    return schedule != OTC


def purchasable_online(schedule: str) -> bool:
    return schedule not in BLOCKED_ONLINE_SCHEDULES
