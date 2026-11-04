"""Domain profiles: how one evidence engine speaks retail revenue or healthcare claims.

Data is stored internally as (id, member, date, status, kind, cents) facts and (member, attribute)
dimension rows. A domain decides only the SQL-facing table/column names, the value vocabulary,
and the labels people see. Verification works on the internal rows, so adding a domain is
configuration, not new verification code.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Domain:
    name: str
    fact: str
    dim: str
    key: str
    member: str
    date: str
    value: str
    attr: str
    status_map: dict = field(default_factory=dict)   # internal -> displayed
    kind_map: dict = field(default_factory=dict)     # internal -> displayed
    item: str = "order"
    items: str = "orders"
    member_noun: str = "customer"
    reversal_noun: str = "refunds"
    metric_noun: str = "revenue"
    money_label: str = "Revenue (USD)"

    @property
    def fact_columns(self):
        return [self.key, self.member, self.date, "status", "kind", self.value]

    @property
    def dim_columns(self):
        return [self.member, self.attr]

    def status(self, internal):
        return self.status_map.get(internal, internal)

    def kind(self, internal):
        return self.kind_map.get(internal, internal)

    def internal_status(self, shown):
        return {v: k for k, v in self.status_map.items()}.get(shown, shown)

    def internal_kind(self, shown):
        return {v: k for k, v in self.kind_map.items()}.get(shown, shown)

    def translate_fact(self, row):
        oid, member, day, status, kind, cents = row
        return (oid, member, day, self.status(status), self.kind(kind), cents)


REVENUE = Domain(
    name="revenue", fact="orders", dim="customers", key="order_id", member="customer_id", date="order_date",
    value="revenue_cents", attr="region",
    status_map={"paid": "paid", "pending": "pending", "cancelled": "cancelled"},
    kind_map={"sale": "sale", "refund": "refund"})

HEALTHCARE = Domain(
    name="healthcare", fact="claims", dim="eligibility", key="claim_id", member="member_id", date="service_date",
    value="paid_cents", attr="plan",
    status_map={"paid": "paid", "pending": "pending", "cancelled": "denied"},
    kind_map={"sale": "claim", "refund": "reversal"},
    item="claim", items="claims", member_noun="member", reversal_noun="claim reversals",
    metric_noun="paid claims", money_label="Paid claims (USD)")

DOMAINS = {d.name: d for d in [REVENUE, HEALTHCARE]}


def get(name):
    return DOMAINS.get(name or "revenue", REVENUE)
