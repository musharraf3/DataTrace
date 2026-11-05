"""Rate metrics: cost per member per month (PMPM) and utilisation per 1,000 member-years.

A rate has a numerator and a denominator, and either one can be wrong. The numerator is the existing
per-claim contract, verified as a complete claim/amount multiset. The denominator is member months:
distinct (member_id, month) pairs inside the contract window, verified as a multiset too. So a
denominator that double-counts coverage lines, keeps members after death or spans the wrong months
fails verification even when the rate it produces looks plausible.

PMPM        = paid cents / member months
Per 1,000   = claims / member months x 12,000   (annualised admissions per 1,000 members)
"""

from collections import Counter
from datetime import date
from fractions import Fraction

RATE_KINDS = {"pmpm": "cost per member per month", "per_1000": "claims per 1,000 member-years"}


class RateError(ValueError):
    pass


def window_months(contract):
    """The calendar months a month-aligned contract window covers, as YYYY-MM strings."""
    start, end = date.fromisoformat(contract["start"]), date.fromisoformat(contract["end_exclusive"])
    if start.day != 1 or end.day != 1:
        raise RateError("A rate contract needs a month-aligned window (start and exclusive end on the 1st).")
    months, year, month = [], start.year, start.month
    while (year, month) < (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    if len(months) > 36:
        raise RateError("A rate window can cover at most 36 months.")
    return months


def validate_rate(rate, contract):
    if not isinstance(rate, dict) or set(rate) != {"kind"} or rate["kind"] not in RATE_KINDS:
        raise RateError(f"Rate must be {{\"kind\": one of {', '.join(RATE_KINDS)}}}.")
    window_months(contract)
    if rate["kind"] == "per_1000" and contract.get("refund_policy") == "include":
        raise RateError("Utilisation per 1,000 counts claims, so reversals must be excluded (refund_policy exclude).")
    return {"kind": rate["kind"]}


def expected_member_months(snapshot, contract):
    """Contract denominator: each (member, month) inside the window exactly once."""
    months = set(window_months(contract))
    return Counter({(member, month): 1 for member, month, _ in snapshot.get("member_months", []) if month in months})


def canonical_denominator_sql(contract, domain):
    months = window_months(contract)  # Validated YYYY-MM strings, safe to inline.
    where = (f"{domain.month} = '{months[0]}'" if len(months) == 1 else
             f"{domain.month} >= '{months[0]}' AND {domain.month} <= '{months[-1]}'")
    return f"SELECT DISTINCT {domain.member}, {domain.month} FROM {domain.enroll} WHERE {where}"


def rate(kind, numerator_cents, numerator_count, member_months):
    """Exact rate as a Fraction: cents PMPM, or claims per 1,000 member-years."""
    if member_months <= 0:
        return None
    if kind == "pmpm":
        return Fraction(numerator_cents, member_months)
    return Fraction(numerator_count * 12000, member_months)


def as_number(value, kind):
    """Display value: dollars PMPM with cents, or claims per 1,000 with one decimal."""
    if value is None:
        return None
    return round(float(value) / 100, 2) if kind == "pmpm" else round(float(value), 1)


def label(value, kind):
    if value is None:
        return "n/a"
    return f"${value:,.2f} PMPM" if kind == "pmpm" else f"{value:,.1f} per 1,000"


def decompose(kind, expected, reported):
    """Split a rate change and a rate error into numerator and denominator effects.

    expected/reported: {"previous"|"current": (cents, count, member_months)}.
    Real change  = (N_c - N_p) / D_c          (cost or utilisation)
                 + N_p * (1/D_c - 1/D_p)      (enrollment)
    Error        = (N_r - N_c) / D_c          (numerator defect)
                 + N_r * (1/D_r - 1/D_c)      (denominator defect)
    """
    def parts(row):
        cents, count, months = row
        return (cents if kind == "pmpm" else count * 12000), months

    (np_, dp), (nc, dc) = parts(expected["previous"]), parts(expected["current"])
    (nq, dq), (nr, dr) = parts(reported["previous"]), parts(reported["current"])
    if min(dp, dc, dq, dr) <= 0:
        return None
    real_numerator, real_enrollment = Fraction(nc - np_, dc), np_ * (Fraction(1, dc) - Fraction(1, dp))
    error_numerator, error_denominator = Fraction(nr - nc, dc), nr * (Fraction(1, dr) - Fraction(1, dc))
    show = lambda value: as_number(value, kind)
    return {"kind": kind, "unit": RATE_KINDS[kind],
            "previous_reported": show(Fraction(nq, dq)), "current_reported": show(Fraction(nr, dr)),
            "reported_change": show(Fraction(nr, dr) - Fraction(nq, dq)),
            "previous_expected": show(Fraction(np_, dp)), "current_expected": show(Fraction(nc, dc)),
            "real_change": show(real_numerator + real_enrollment),
            "real_change_from_numerator": show(real_numerator), "real_change_from_enrollment": show(real_enrollment),
            "reporting_error": show(error_numerator + error_denominator),
            "error_from_numerator": show(error_numerator), "error_from_denominator": show(error_denominator)}


def delta(value, kind):
    """A signed change in the rate's own unit: +$46.64 PMPM or +43.4 per 1,000."""
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else "+"
    return f"{sign}${abs(value):,.2f} PMPM" if kind == "pmpm" else f"{sign}{abs(value):,.1f} per 1,000"
