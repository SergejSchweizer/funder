# EU Tax And Cost Architecture

Last reviewed: 2026-07-17

## Purpose

Camovar is intended to support private investors across the European Union. Austrian tax and Flatex Austria behavior may be the first implemented jurisdiction and broker profile, but neither may become a hard-coded assumption in portfolio mathematics, income analysis, backtesting, or recommendation logic.

This document extends the Production Portfolio Product PR Stack and the production implementation map with jurisdiction-neutral contracts, versioned country adapters, broker and venue cost profiles, and after-tax cash-flow requirements.

The canonical backlog remains `BACKLOG.md`. This document records the implementation architecture and additional acceptance criteria that must be reflected when PR62 through PR68 are implemented.

## Product Objective

Camovar must optimize and compare portfolios using the investor's actual economic result:

```text
market return
+ cash distributions
- source-country withholding tax
- residence-country capital-income tax
- fund-specific taxable deemed income
- transaction fees
- venue and settlement fees
- bid/ask spread and slippage
- foreign-exchange costs
- recurring broker and custody costs
- country-specific transaction taxes or levies
= after-tax, after-cost portfolio result
```

For income-oriented users, the primary output is not gross distribution yield. It is stable spendable net cash flow while preserving capital under explicit nominal or real-capital constraints.

## Architectural Principles

1. The core engine must not import an Austrian, German, French, or other country module directly.
2. Country behavior is selected through a jurisdiction registry keyed by ISO country code and rule version.
3. Broker pricing is separate from tax residence and separate from trading venue costs.
4. Source-country withholding, investor-residence taxation, fund domicile, broker jurisdiction, trading venue, and account type are separate dimensions.
5. Tax rates, allowances, thresholds, and effective dates must not be hard-coded in portfolio objectives.
6. Every rule set is immutable, versioned, source-attributed, and bounded by `valid_from` and optional `valid_to` dates.
7. Unsupported or insufficiently verified rules produce `unavailable`, never a plausible zero tax or zero cost.
8. Camovar is a calculation and decision-support system, not a tax-filing or legal-advice system.
9. Gross, after-tax, and after-tax-after-cost results must always remain separately visible.
10. Historical backtests must apply rules valid at the simulated event date, not only today's rule set.

## Required Jurisdiction Dimensions

A complete calculation request must distinguish at least:

```text
investor_tax_residence
investor_type
account_type
broker_id
broker_country
base_currency
instrument_type
instrument_domicile
fund_tax_status
income_source_country
listing_currency
trading_venue
settlement_country
calculation_date
```

Examples:

- an Austrian resident using a German broker;
- a German resident buying an Irish UCITS ETF on Xetra;
- a French resident receiving US-source dividends through a Luxembourg fund;
- the same investor using a tax-advantaged or ordinary account;
- identical instruments traded through different brokers or venues.

These cases must resolve to different tax and cost plans where the relevant rules differ.

## Target Package Structure

```text
src/camovar/tax/
    __init__.py
    contracts.py
    events.py
    engine.py
    registry.py
    cost_basis.py
    withholding.py
    allowances.py
    reporting.py
    validation.py
    countries/
        __init__.py
        at/
            __init__.py
            contracts.py
            rules.py
            funds.py
            loss_offset.py
            sources.py
        de/
        fr/
        it/
        es/
        nl/
        be/
        ...

src/camovar/costs/
    __init__.py
    contracts.py
    engine.py
    registry.py
    execution.py
    fx.py
    recurring.py
    transaction_taxes.py
    venues/
        xetra.py
        tradegate.py
        gettex.py
        ...
    brokers/
        flatex_at/
        flatex_de/
        scalable_de/
        degiro_nl/
        ...
```

Country adapters may begin as one package per implemented jurisdiction. The registry must support every EU member-state code from the start, but an unimplemented country must resolve to an explicit unsupported status.

## Jurisdiction-Neutral Tax Contracts

`src/camovar/tax/contracts.py` should define immutable contracts such as:

```python
@dataclass(frozen=True)
class InvestorTaxProfile:
    residence_country: str
    investor_type: str
    account_type: str
    filing_currency: str
    tax_year: int
    attributes: Mapping[str, str | int | float | bool]
```

```python
@dataclass(frozen=True)
class TaxRuleSetRef:
    jurisdiction: str
    rule_set_id: str
    version: str
    valid_from: date
    valid_to: date | None
    reviewed_at: date
    verification_status: str
    source_refs: tuple[str, ...]
```

```python
@dataclass(frozen=True)
class TaxEvent:
    event_id: str
    event_date: date
    event_type: str
    instrument_id: str
    gross_amount: Decimal
    currency: str
    source_country: str | None
    metadata: Mapping[str, str]
```

```python
@dataclass(frozen=True)
class TaxCalculationResult:
    gross_amount_base: Decimal
    source_withholding_tax: Decimal
    residence_tax_before_credits: Decimal
    foreign_tax_credit: Decimal
    residence_tax_after_credits: Decimal
    allowance_used: Decimal
    realized_loss_offset: Decimal
    total_tax: Decimal
    net_amount: Decimal
    status: str
    reasons: tuple[str, ...]
    rule_set_ref: TaxRuleSetRef
```

Supported event types should include at least:

```text
distribution
interest
realized_gain
realized_loss
deemed_distribution
accumulating_fund_income
fund_tax_adjustment
foreign_withholding
corporate_action
fee_tax_adjustment
```

## Country Adapter Protocol

`src/camovar/tax/registry.py` should resolve a country adapter implementing a stable protocol:

```python
class CountryTaxAdapter(Protocol):
    def validate_profile(self, profile: InvestorTaxProfile) -> ValidationResult: ...
    def classify_instrument(self, instrument: InstrumentTaxFacts) -> TaxClassification: ...
    def calculate_event(self, request: TaxEventRequest) -> TaxCalculationResult: ...
    def update_cost_basis(self, request: CostBasisRequest) -> CostBasisResult: ...
    def apply_loss_offset(self, request: LossOffsetRequest) -> LossOffsetResult: ...
    def close_tax_year(self, request: TaxYearCloseRequest) -> TaxYearResult: ...
```

The portfolio and income modules may depend on this protocol and the neutral result contracts, but never on `camovar.tax.countries.at` or another concrete adapter.

## Rule Data Versus Calculation Code

Country modules should separate stable calculation mechanics from frequently changing rates and thresholds.

```text
countries/at/rules.py
    calculation mechanics

resources/tax/AT/2026.json
    rates, thresholds, allowances, valid dates, source references
```

The same pattern should be usable for all jurisdictions.

Every rule resource must contain:

```text
jurisdiction
rule_version
valid_from
valid_to
investor_types
account_types
rates
allowances
thresholds
loss_offset_rules
foreign_tax_credit_rules
cost_basis_method
fund_tax_rules
source_documents
reviewed_at
verification_status
```

A change in tax law produces a new immutable version. Existing analyses retain references to the historical version used.

## Fund-Specific Tax Data

Tax treatment must not be inferred solely from `UCITS`, domicile, or distribution policy.

Camovar should support country-specific fund-tax data providers through ports:

```python
class FundTaxDataPort(Protocol):
    def resolve_tax_facts(
        self,
        *,
        isin: str,
        jurisdiction: str,
        tax_year: int,
    ) -> FundTaxFactsResult: ...
```

Austria may initially use OeKB-derived tax facts. Other countries may require different official or market data sources. The core contract must therefore be generic and record:

```text
isin
jurisdiction
tax_year
fund_tax_classification
reporting_status
distribution_tax_base
deemed_income_tax_base
foreign_tax_credit
cost_basis_adjustment
source_ref
verification_status
```

A country adapter decides how those facts affect the investor. The fund-data adapter does not calculate the investor's final tax liability.

## Cost-Basis Methods

Different jurisdictions may use different disposal and acquisition-cost rules. Camovar must not globally assume moving average, FIFO, LIFO, or specific-lot identification.

`src/camovar/tax/cost_basis.py` should define a strategy protocol:

```python
class CostBasisStrategy(Protocol):
    def acquire(self, state: PositionTaxState, lot: AcquisitionLot) -> PositionTaxState: ...
    def dispose(self, state: PositionTaxState, disposal: Disposal) -> DisposalTaxResult: ...
    def adjust(self, state: PositionTaxState, adjustment: BasisAdjustment) -> PositionTaxState: ...
```

Country rule sets select the permitted strategy and any account-specific variation.

Persisted position tax state must include:

```text
jurisdiction
rule_set_id
account_id
instrument_id
quantity
cost_basis_base_currency
acquisition_lots_or_average_state
fund_basis_adjustments
realized_gain_ytd
realized_loss_ytd
foreign_tax_credit_ytd
last_event_id
```

## Loss Offsetting And Tax-Year State

The tax engine must maintain explicit tax-year state because losses, allowances, and credits often depend on category, account, broker, and calendar year.

Required neutral state:

```text
tax_year
income_by_category
realized_gains_by_category
realized_losses_by_category
allowances_used
foreign_tax_credits_used
withholding_paid
residence_tax_paid
carry_forward_state
broker_withholding_state
```

Country adapters own category compatibility, annual reset, carry-forward behavior, broker withholding assumptions, and filing adjustments.

## Broker, Venue, And Jurisdiction Cost Separation

Costs must be composed from independent profiles:

```text
BrokerCostProfile
+ VenueCostProfile
+ ExecutionCostModel
+ FXCostProfile
+ JurisdictionTransactionTaxProfile
+ RecurringAccountCostProfile
= TotalExecutionAndHoldingCost
```

### Broker cost profile

Examples:

```text
fixed order fee
variable order fee
minimum and maximum fee
savings-plan fee
custody fee
account fee
fund handling fee
cash interest or negative interest
FX conversion markup
third-party pass-through fees
promotion validity period
```

### Venue cost profile

Examples:

```text
exchange fee
settlement fee
clearing fee
minimum venue charge
auction versus continuous trading fee
currency
```

### Execution model

Examples:

```text
half-spread estimate
slippage model
market-impact model
order-size bucket
liquidity class
order type
execution time policy
```

### Jurisdiction transaction costs

Examples:

```text
financial transaction tax
stamp duty
exchange levy
regulatory fee
country-specific acquisition or disposal tax
```

These are not ordinary broker fees and should be modeled by jurisdiction-specific cost adapters.

## Cost Contracts

`src/camovar/costs/contracts.py` should define:

```python
@dataclass(frozen=True)
class ExecutionContext:
    investor_country: str
    broker_id: str
    broker_country: str
    venue_id: str
    instrument_id: str
    instrument_type: str
    side: str
    quantity: Decimal
    price: Decimal
    trade_currency: str
    base_currency: str
    trade_date: date
```

```python
@dataclass(frozen=True)
class CostBreakdown:
    broker_fee: Decimal
    venue_fee: Decimal
    settlement_fee: Decimal
    estimated_spread_cost: Decimal
    estimated_slippage: Decimal
    fx_cost: Decimal
    transaction_tax: Decimal
    recurring_cost_allocation: Decimal
    total_cost: Decimal
    status: str
    profile_refs: tuple[str, ...]
```

Broker profiles and venue profiles must be versioned by validity date. Historical simulations resolve the profile valid on the simulated trade date.

## Calculation Status And Confidence

Every tax or cost result must use one of:

```text
exact
verified_estimate
user_supplied_estimate
unavailable
unsupported
```

A production candidate may require a configurable minimum status. For example:

```text
minimum_tax_status = verified_estimate
minimum_cost_status = verified_estimate
```

Camovar must propagate unavailable or unsupported states into portfolio and recommendation outputs. Missing rules may not be replaced by zero.

## After-Tax Cash-Flow Engine

Create a neutral orchestration layer:

```text
src/camovar/cashflow/
    contracts.py
    engine.py
    monthly.py
    sustainability.py
    projections.py
```

The engine consumes:

```text
portfolio holdings
market events
trade events
country tax adapter
tax-year state
broker and venue profiles
FX data
income policy
withdrawal policy
```

It produces:

```text
gross_cash_flow
source_withholding_tax
residence_tax
foreign_tax_credit
transaction_costs
recurring_costs
net_spendable_cash_flow
reinvested_cash_flow
withdrawn_cash_flow
capital_after_cash_flow
nominal_capital_change
real_capital_change
```

Monthly output must distinguish event timing from economic accrual. Tax payment timing and broker withholding timing are jurisdiction-specific and must be configurable.

## Portfolio Objective Integration

Portfolio optimizers must not directly calculate country taxes. They consume after-tax projections or differentiable approximations produced by the cash-flow layer.

Required objectives and constraints include:

```text
maximize conservative net monthly income
maximize after-tax total return
minimize tax drag
minimize cost drag
minimize turnover
limit NAV erosion
limit expected shortfall
limit drawdown
preserve nominal capital
preserve real capital
minimum net annual income
minimum income stability
```

Camovar must compare at least:

```text
natural distribution income
synthetic income through periodic sales
hybrid distribution and sale income
full reinvestment baseline
```

The best gross-yield portfolio must not automatically win.

## Persistence Contracts

Add immutable datasets or equivalent artifact contracts for:

```text
tax_rule_sets
fund_tax_facts
tax_events
tax_calculation_results
tax_year_states
position_cost_basis
broker_cost_profiles
venue_cost_profiles
transaction_tax_profiles
execution_cost_events
recurring_cost_events
portfolio_cashflows
monthly_net_income
after_tax_portfolio_metrics
cashflow_sustainability
```

Every persisted result must include:

```text
artifact_id
calculation_date
jurisdiction
rule_set_id
broker_profile_id
venue_profile_id
input_artifact_ids
status
reason_codes
algorithm_version
production_eligible
```

## Backtest Requirements

Walk-forward and rebalance simulations must apply the correct historical tax and cost profiles at each event date.

Tests must prove:

- no future rule version is used before its valid date;
- a tax-rate change creates different results across the effective date;
- the same portfolio produces different net outcomes for different investor countries;
- the same tax residence with different brokers produces different costs but the same residence-tax rules;
- the same broker with different venues produces different venue and execution costs;
- loss-offset state does not leak between tax years;
- foreign tax credits are capped according to the selected country adapter;
- unavailable country rules block production labeling;
- gross, after-tax, and after-cost series reconcile exactly;
- repeated simulations with unchanged inputs are deterministic and idempotent.

## EU Country Rollout Strategy

Do not implement 27 jurisdictions simultaneously. Build the platform contract once, then add verified country adapters incrementally.

Suggested sequence:

```text
Phase 1: jurisdiction-neutral contracts and registries
Phase 2: Austria reference adapter and Flatex Austria profile
Phase 3: Germany reference adapter and major German broker profiles
Phase 4: France, Italy, Spain, Netherlands, and Belgium
Phase 5: remaining EU member states based on user demand and verified data availability
```

Country readiness table:

```text
country_code
adapter_status
supported_investor_types
supported_account_types
supported_instrument_types
fund_tax_data_status
loss_offset_status
cost_basis_status
broker_withholding_status
last_legal_review
rule_version
known_limitations
```

The UI and API must expose this table and prevent users from assuming that all EU countries have equal calculation coverage.

## Proposed Backlog Extension

PR62 should be expanded or followed by a strict sub-stack:

### PR62A. Jurisdiction-Neutral Tax And Cost Contracts

Create `camovar.tax`, `camovar.costs`, and `camovar.cashflow` public contracts, registries, status model, immutable rule references, cost-basis protocol, and artifact schemas. Add all EU country codes to the registry with unsupported placeholders. No concrete tax rate is hard-coded in core modules.

### PR62B. Austria Tax And Broker Reference Adapter

Implement Austria as the first verified country adapter, including private-investor capital-income events, fund-tax facts, tax-year state, supported loss-offset behavior, Austrian cost-basis behavior, and an initial Flatex Austria cost profile. Keep all behavior behind the neutral interfaces.

### PR62C. Historical Rule Resolution And Tax-Year Engine

Add effective-date rule lookup, historical rule versions, tax-year state, allowances, foreign-tax credits, loss offsetting, and deterministic year close. Backtests resolve the rule version valid at each event date.

### PR62D. Broker, Venue, FX, And Transaction-Cost Engine

Implement composable broker, venue, execution, FX, recurring, and jurisdiction-transaction-cost profiles. Replace global transaction-cost-rate assumptions in production paths.

### PR62E. Net Cash Flow And Sustainability Metrics

Generate gross, after-tax, and after-cost cash flows; natural, synthetic, and hybrid income strategies; stable monthly net-income metrics; nominal and real capital preservation; tax drag; cost drag; and sustainability warnings.

### PR62F. EU Adapter Expansion Framework

Add country-adapter templates, source-reference requirements, legal-review metadata, adapter conformance tests, readiness reporting, and documentation for adding further EU jurisdictions without changing portfolio core code.

PR63 and later production portfolio work must depend on PR62E. EU-wide deployment may expose only jurisdictions whose adapters meet the configured verification threshold.

## Acceptance Gate For EU-Wide Claims

Camovar may describe itself as architecturally EU-ready when:

- the core has no direct Austria-specific imports;
- all country selection occurs through registries and neutral protocols;
- every rule and profile is versioned and effective-dated;
- unsupported countries return explicit status;
- tax residence, fund domicile, source country, broker country, and venue are modeled separately;
- at least two country adapters produce different verified results from the same market events;
- country conformance tests pass;
- the UI clearly labels jurisdiction coverage.

Camovar may describe a specific country as supported only when that country's adapter, fund-tax inputs, cost-basis method, loss-offset behavior, broker assumptions, source references, and known limitations are documented and tested.
