"""Jurisdiction-neutral tax contracts, registries, and cost-basis protocol.

See docs/backlog/eu-tax-cost-architecture.md for the full architecture. This
package must never hard-code a concrete country's tax rate, allowance, or
threshold; those belong in versioned per-country rule resources consumed by
a `camovar.tax.registry.CountryTaxAdapter` implementation (PR62B onward).
"""
