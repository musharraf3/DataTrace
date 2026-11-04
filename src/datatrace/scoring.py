"""Answer-quality scoring beyond the classification label.

Two questions a finance or claims lead actually asks:
1. Did the explanation name the real root cause? (keyword rubric per incident family)
2. Did it put the right dollar amounts on "real change" and "reporting error"? (within 1%)
Ground truth comes from the deterministic contract reconciliation, never from a model.
"""

import re

_AMOUNT = re.compile(r"\$?\s?([-−]?\d[\d,]*(?:\.\d+)?)\s?(k|K|thousand)?")


def _family(family):
    return family.split("_", 1)[1] if family.startswith(("realistic_", "healthcare_", "synpuf_")) else family


def root_cause_named(family, text, classification=None):
    t = (text or "").lower()
    f = _family(family)
    if f in {"duplicate_join", "crm_migration", "eligibility_spans"}:
        return bool(re.search(r"duplicat|fan-?out|multipl|double", t)) and bool(re.search(r"join|customer|member|eligib|enrol", t))
    if f == "dropped_records":
        return bool(re.search(r"inner join|unmatched|drop|missing|exclud|lost", t))
    if f in {"date_filter", "cutoff_change", "service_date_cutoff"}:
        return bool(re.search(r"<=|inclusive|boundary|end date|cut-?off|-12-01|-11-01|dec(ember)? 1|nov(ember)? 1", t))
    if f in {"status_filter", "pending_counted"}:
        return "pending" in t
    if f in {"growth", "holiday_growth", "runout_growth"}:
        return classification == "genuine_change"
    if f in {"ambiguous", "refund_policy", "reversal_policy"}:
        return bool(re.search(r"refund|reversal", t))
    return False


def amounts(text):
    values = []
    for match in _AMOUNT.finditer(text or ""):
        try:
            value = abs(float(match.group(1).replace(",", "").replace("−", "-")))
        except ValueError:
            continue
        values.append(value * 1000 if match.group(2) else value)
    return values


def _mentions(cents, values):
    target = abs(cents) / 100
    if target == 0:
        return True
    return any(abs(v - target) <= max(0.01 * target, 1.0) for v in values)


def dollar_split_correct(text, reconciliation):
    """True when both the real change and the reporting error appear with the right amounts."""
    if not reconciliation:
        return None
    values = amounts(text)
    error = reconciliation["current_error_cents"]
    return _mentions(reconciliation["underlying_change_cents"], values) and (error == 0 or _mentions(error, values))
