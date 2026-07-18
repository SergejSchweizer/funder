"""Jurisdiction-neutral cost contracts, registries, and status model (PR62A).

Broker pricing, trading-venue costs, execution costs, FX costs, and
jurisdiction transaction taxes are independent, composable profiles (see
docs/backlog/eu-tax-cost-architecture.md, "Broker, Venue, And Jurisdiction
Cost Separation"). No concrete fee, spread, or tax rate is hard-coded here;
those belong in versioned broker/venue/jurisdiction profile implementations
registered through `CostProfileRegistry`.
"""
