"""
"Does it actually work on this machine?" runner. Plain Python (testable without Django).

Each check is a function that returns None (OK), raises (FAIL), or returns a string (WARN). Messages must never contain
secrets: the runner shortens them and the checks only describe what is wrong, not the values.
"""
import re
from dataclasses import dataclass

OK, WARN, FAIL = "OK", "WARN", "FAIL"


class Warn(Exception):
    """Raise (or return a string) for a problem that does not stop the app."""


@dataclass
class Result:
    name: str
    status: str
    message: str = ""


_URI_CREDENTIALS = re.compile(r"://[^/@\s]+:[^/@\s]+@")


def _clean(text: str, limit: int) -> str:
    return _URI_CREDENTIALS.sub("://***@", str(text))[:limit]


def run_checks(checks) -> list[Result]:
    results = []
    for name, fn in checks:
        try:
            outcome = fn()
            results.append(Result(name, WARN, _clean(outcome, 200)) if isinstance(outcome, str) and outcome else Result(name, OK))
        except Warn as exc:
            results.append(Result(name, WARN, _clean(exc, 200)))
        except Exception as exc:                                    # noqa: BLE001 - a doctor must survive anything
            results.append(Result(name, FAIL, f"{type(exc).__name__}: {_clean(exc, 160)}"))
    return results


def summarize(results) -> tuple[str, bool]:
    lines = [f"{r.status:<5}{r.name}" + (f"  - {r.message}" if r.message else "") for r in results]
    failed = sum(r.status == FAIL for r in results)
    warned = sum(r.status == WARN for r in results)
    lines.append(f"\n{len(results) - failed - warned} ok, {warned} warnings, {failed} failed")
    return "\n".join(lines), failed == 0
