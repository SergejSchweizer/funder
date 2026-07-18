"""Country tax-adapter registry (PR62A).

The core engine must never import a concrete country module directly
(see docs/backlog/eu-tax-cost-architecture.md, "Architectural Principles").
Country behavior is selected exclusively through this registry, keyed by
ISO 3166-1 alpha-2 country code. Every EU member-state code is known to the
registry from the start; an unimplemented country resolves to an explicit
`unsupported` status rather than a plausible default.
"""

from __future__ import annotations

from typing import Protocol

from founder.calculation_status import UNSUPPORTED
from founder.tax.contracts import (
    CostBasisRequest,
    CostBasisResult,
    InstrumentTaxFacts,
    LossOffsetRequest,
    LossOffsetResult,
    TaxCalculationResult,
    TaxClassification,
    TaxEventRequest,
    TaxYearCloseRequest,
    TaxYearResult,
    ValidationResult,
)
from founder.tax.contracts import InvestorTaxProfile as _InvestorTaxProfile

# ISO 3166-1 alpha-2 codes for the 27 EU member states.
EU_COUNTRY_CODES: frozenset[str] = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)


class CountryTaxAdapter(Protocol):
    """A single jurisdiction's tax calculation behavior."""

    def validate_profile(self, profile: _InvestorTaxProfile) -> ValidationResult: ...

    def classify_instrument(self, instrument: InstrumentTaxFacts) -> TaxClassification: ...

    def calculate_event(self, request: TaxEventRequest) -> TaxCalculationResult: ...

    def update_cost_basis(self, request: CostBasisRequest) -> CostBasisResult: ...

    def apply_loss_offset(self, request: LossOffsetRequest) -> LossOffsetResult: ...

    def close_tax_year(self, request: TaxYearCloseRequest) -> TaxYearResult: ...


class UnsupportedCountryError(LookupError):
    """Raised when a country code has no registered adapter."""


class CountryTaxRegistry:
    """A registry of country codes to `CountryTaxAdapter` implementations.

    Every EU country code is known (`is_known_country`), but only codes with
    a registered adapter are `is_supported`. Resolving an unregistered known
    code raises `UnsupportedCountryError` rather than falling back to a
    default adapter or a plausible zero-tax result.
    """

    def __init__(self, known_country_codes: frozenset[str] = EU_COUNTRY_CODES) -> None:
        self._known_country_codes = known_country_codes
        self._adapters: dict[str, CountryTaxAdapter] = {}

    def is_known_country(self, country_code: str) -> bool:
        return country_code in self._known_country_codes

    def is_supported(self, country_code: str) -> bool:
        return country_code in self._adapters

    def register(self, country_code: str, adapter: CountryTaxAdapter) -> None:
        if country_code not in self._known_country_codes:
            raise ValueError(
                f"country_code {country_code!r} is not a known jurisdiction; "
                "add it to the registry's known-country set first"
            )
        self._adapters[country_code] = adapter

    def resolve(self, country_code: str) -> CountryTaxAdapter:
        adapter = self._adapters.get(country_code)
        if adapter is None:
            if country_code in self._known_country_codes:
                raise UnsupportedCountryError(
                    f"{country_code} is a known jurisdiction but has no registered "
                    f"tax adapter yet (status={UNSUPPORTED})"
                )
            raise UnsupportedCountryError(f"{country_code} is not a known jurisdiction")
        return adapter

    def known_country_codes(self) -> frozenset[str]:
        return self._known_country_codes

    def supported_country_codes(self) -> frozenset[str]:
        return frozenset(self._adapters)


__all__ = [
    "EU_COUNTRY_CODES",
    "CountryTaxAdapter",
    "CountryTaxRegistry",
    "UnsupportedCountryError",
]
