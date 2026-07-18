"""Neutral after-tax, after-cost cash-flow contracts (PR62A).

`founder.cashflow` orchestrates `founder.tax` and `founder.costs` results
into a single investor-facing cash-flow result. It must never calculate
country taxes or broker costs itself; see docs/backlog/eu-tax-cost-architecture.md,
"After-Tax Cash-Flow Engine".
"""
