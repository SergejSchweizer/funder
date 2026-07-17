# Founder Goals

Last reviewed: 2026-07-17

## Purpose

Founder is intended to become a practical portfolio construction and investment analysis tool for private investors, with a later path to public access.

The project should help a user move from a broad ETF and fund universe to a transparent, risk-aware, investable portfolio. It should not merely calculate an efficient frontier or rank funds by historical return. It should combine data quality checks, fund analysis, portfolio construction, out-of-sample validation, rebalancing, costs, and human-readable explanations.

The initial personal use case is portfolio construction with UCITS ETFs and exchange-traded funds available through Flatex, using EODHD end-of-day market data. Income-oriented and monthly distributing funds are an important specialization, but the architecture should remain useful for defensive, balanced, growth, and total-return portfolios.

## Product Vision

Founder should answer five questions:

1. Which instruments are suitable for the user's objective?
2. Which instruments add genuinely different risk exposure?
3. How should capital be allocated under explicit constraints?
4. How robust would the portfolio have been outside the estimation period and after costs?
5. What trades and future monitoring actions are required?

The user should receive more than one mathematically optimal result. Founder should compare several robust portfolio methods under the same assumptions and expose the trade-offs.

The final output should include:

- selected and excluded instruments with reasons;
- target weights and risk contributions;
- expected income, risk, drawdown, and concentration diagnostics;
- historical and walk-forward performance;
- transaction-cost and turnover estimates;
- stress and tail-risk results;
- differences from the current portfolio;
- a Flatex-oriented trade-preparation export;
- warnings about weak data, short history, unstable distributions, or excessive concentration.

## Guiding Principles

### Risk first

Expected returns are difficult to estimate and highly unstable. The first trusted production portfolios should therefore rely primarily on robust risk estimates, diversification, explicit constraints, and out-of-sample validation.

### No single optimizer is universally best

Founder should implement a model comparison framework rather than declare one method universally optimal. Equal Weight and Inverse Volatility should remain permanent baselines.

### Out-of-sample evidence over in-sample fit

A portfolio method should be preferred only when it behaves robustly in walk-forward tests, under multiple estimation windows, after transaction costs, and across adverse periods.

### Explainability

Every portfolio recommendation must be traceable to data, constraints, model inputs, and diagnostics. A user should understand why a fund received a particular weight or was excluded.

### Reproducibility

Every analysis must use persisted selections, versioned dataset contracts, deterministic run identifiers, explicit assumptions, and reproducible outputs.

### Decision support, not guaranteed performance

Founder should not imply certainty, guaranteed income, or guaranteed returns. It should present estimated outcomes, uncertainty, risks, and data limitations.

## Target User Workflows

### Build a new portfolio

```text
Investment objective
  -> universe and eligibility filters
  -> data-quality validation
  -> individual fund analysis
  -> redundancy and diversification analysis
  -> portfolio model comparison
  -> walk-forward and stress validation
  -> selected target portfolio
  -> trade-preparation export
```

### Analyze an existing portfolio

```text
Current positions
  -> current weights and exposures
  -> return, risk, income, and drawdown analysis
  -> concentration and overlap diagnostics
  -> comparison with alternative portfolios
  -> transition plan with turnover and estimated costs
```

### Monitor a portfolio

```text
Updated prices and distributions
  -> metric refresh
  -> drift and risk checks
  -> distribution-cut and NAV-erosion checks
  -> rebalance decision
  -> updated report and optional alert
```

## Data Requirements

### Current core data

Founder can already use the following information for a strong first version:

- instrument metadata and ISINs;
- canonical exchange listings;
- adjusted and unadjusted end-of-day prices;
- volume;
- dividends and distributions;
- splits;
- daily returns;
- univariate statistics;
- pairwise covariance and correlation;
- persisted metadata and metric selections.

### Additional data required for a stronger public product

The following fields should be added or sourced where possible:

- total expense ratio and ongoing charges;
- fund inception date and usable track-record length;
- fund size and assets under management;
- issuer and fund family;
- benchmark and underlying index;
- asset-class, country, sector, and currency exposures;
- holdings and holdings overlap;
- replication method;
- currency-hedging status;
- observed or estimated bid-ask spread;
- fund domicile and relevant tax metadata;
- Flatex fees, taxes, actual distributions, positions, and cost basis;
- foreign-exchange time series for a configurable portfolio base currency.

A public hosted version must confirm market-data display, derived-data, and redistribution rights before exposing provider data or derived datasets to users.

## Analysis Layers

## 1. Universe And Eligibility Analysis

Founder should reduce the broad instrument universe before portfolio optimization.

Required checks include:

- one canonical listing per ISIN;
- sufficient quote coverage;
- minimum history, preferably at least 252 observations and normally 504 to 756 daily observations for production use;
- valid and non-stale prices;
- no unexplained gaps or duplicate rows;
- sufficient liquidity or a documented liquidity proxy;
- supported listing currency and portfolio base-currency conversion;
- explicit fund type, distribution policy, and eligibility status;
- exclusion of instruments with unreliable or insufficient data.

Selection should remain a persisted, versioned artifact. Optimization must never silently operate on an ad hoc or changing universe.

## 2. Individual Fund Analysis

Each fund should be analyzed independently before pairwise and portfolio analysis.

### Return and trend metrics

- total return;
- price return;
- cumulative log return;
- CAGR;
- annualized arithmetic and geometric return;
- rolling returns over several horizons;
- positive-day and positive-month ratios;
- log-price trend and trend strength;
- best and worst daily, monthly, and quarterly periods.

### Risk metrics

- annualized volatility;
- downside deviation;
- historical VaR;
- historical Expected Shortfall or CVaR;
- maximum drawdown;
- drawdown duration and recovery duration;
- ulcer index;
- Sharpe ratio;
- Sortino ratio;
- Calmar ratio;
- skewness and excess kurtosis;
- rolling volatility and rolling tail risk.

### Data-quality diagnostics

Invalid prices must not be converted into zero returns. They should be excluded or rejected and reported as data-quality failures.

Metrics must include observation counts, date ranges, availability reasons, and confidence flags. Very short histories must not receive the same status as mature funds.

## 3. Income And Distribution Analysis

Income analysis is a core differentiator for Founder.

Founder should distinguish distribution frequency from distribution quality. Counting distribution events alone is insufficient.

Required metrics include:

- distribution frequency;
- trailing twelve-month distribution amount;
- trailing distribution yield;
- average and median monthly distribution;
- conservative monthly distribution estimate, such as the lower 20th percentile;
- distribution variability and coefficient of variation;
- number of distribution cuts;
- largest distribution cut;
- longest sequence of falling distributions;
- distribution growth or decline trend;
- price return versus total return;
- distribution-to-total-return gap;
- NAV or price erosion;
- income per unit of Expected Shortfall;
- estimated gross and net income after configurable taxes and fees.

A high distribution rate must not be treated as a high expected return. Founder should explicitly warn when distributions appear unsupported by total return or are accompanied by persistent NAV erosion.

A useful income-efficiency metric is:

```text
Income Efficiency = sustainable net annual income / Expected Shortfall
```

The sustainable income estimate should be conservative and should not rely only on the latest payment annualized.

## 4. Pairwise And Diversification Analysis

Founder should measure whether instruments add genuine diversification.

Required pairwise measures include:

- Pearson correlation;
- Spearman correlation;
- covariance;
- beta in both directions;
- common observation count and common date range;
- rolling correlation;
- downside correlation;
- stress-period correlation;
- optional return-distance and clustering distance.

Pair statistics must require a minimum number of common observations.

The pairwise engine must not create millions of tiny files or materialize all possible pairs in memory. It should support partitioned datasets, streaming or blocked computation, threshold filters, and top-k relationships per instrument.

Dense covariance matrices should be built only for the final candidate set used by an optimizer.

## Risk Models

Founder should support multiple covariance and risk estimators.

### Required production estimators

- sample covariance as a diagnostic baseline;
- Ledoit-Wolf shrinkage covariance;
- exponentially weighted covariance;
- configurable rolling and expanding estimation windows.

### Diagnostics

Every covariance estimate should expose:

- estimation period;
- observation count;
- missing pair count;
- positive-semidefinite status;
- condition number or stability category;
- shrinkage intensity where applicable;
- handling of missing observations;
- base return frequency.

Raw sample covariance should not be the only production risk model because highly correlated ETFs and estimation noise can produce unstable allocations.

## Portfolio Construction Methods

Founder should implement and compare the following methods.

### 1. Equal Weight

Equal Weight is the mandatory benchmark:

```text
w_i = 1 / N
```

It is simple, transparent, and difficult for unstable models to outperform consistently after costs.

### 2. Inverse Volatility

```text
w_i proportional to 1 / sigma_i
```

This is a robust and explainable risk-based baseline that does not require expected-return estimates.

### 3. Constrained Minimum Variance

```text
minimize w' Sigma w
```

Subject to long-only, full-investment, concentration, group, history, liquidity, and optional turnover constraints.

The production implementation should use a numerical quadratic-programming solver and a shrinkage covariance estimator.

### 4. Equal Risk Contribution

Each asset should contribute approximately the same fraction of portfolio risk:

```text
RC_i = w_i * (Sigma w)_i
```

Founder should use a numerical solver, record convergence diagnostics, and expose marginal, absolute, and percentage risk contributions.

### 5. True Hierarchical Risk Parity

Founder should implement actual Hierarchical Risk Parity using:

1. a covariance and correlation matrix;
2. a correlation-based distance matrix;
3. hierarchical clustering;
4. quasi-diagonal ordering;
5. recursive bisection based on cluster variance.

A simple alphabetical split or midpoint recursion is not sufficient and must remain only a temporary deterministic baseline.

### 6. Maximum Diversification

Founder should maximize the diversification ratio under the same production constraints and compare it with Minimum Variance and Equal Risk Contribution.

### 7. Minimum CVaR

Founder should minimize historical or scenario-based CVaR under long-only and concentration constraints.

This is particularly important for defensive and income-oriented portfolios because variance penalizes positive and negative deviations equally, while CVaR focuses on severe losses.

### 8. Maximum Sharpe As A Comparison Method

Maximum Sharpe should be calculated for research and comparison, but it should not be the default recommendation while expected returns are estimated from simple historical averages.

A future production expected-return layer may include:

- Black-Litterman;
- factor models;
- momentum or trend overlays;
- regime-dependent expectations;
- explicit user views.

## Portfolio Constraints

Constraints are part of the investment model and must be explicit, stored, and reported.

Founder should support:

- weights summing to one;
- long-only portfolios by default;
- minimum and maximum instrument weights;
- issuer limits;
- asset-class limits;
- country and region limits;
- sector limits;
- currency limits;
- strategy limits, such as covered-call exposure;
- limits for young or short-history funds;
- limits for crypto-equity and other high-risk themes;
- minimum liquidity and quote coverage;
- minimum and target income;
- maximum volatility, drawdown, CVaR, and turnover;
- maximum change from current weights;
- minimum trade size and whole-share constraints for trade preparation.

## Portfolio Profiles

The public tool should expose understandable profiles while retaining advanced configuration.

### Defensive

Primary objective: minimize tail risk and drawdown.

Preferred methods:

- Minimum CVaR;
- shrinkage Minimum Variance;
- Equal Risk Contribution.

### Balanced

Primary objective: robust diversification with controlled risk.

Preferred methods:

- True HRP;
- Equal Risk Contribution;
- shrinkage Minimum Variance;
- ensemble portfolio.

### Income

Primary objective: maximize sustainable net income subject to risk, erosion, and concentration limits.

Conceptual objective:

```text
maximize
    sustainable net income
    - lambda_1 * CVaR
    - lambda_2 * NAV erosion
    - lambda_3 * turnover and costs
    - lambda_4 * concentration risk
```

### Growth

Primary objective: long-term total return under a configurable risk budget.

Growth should still use diversification and risk constraints. Maximum Sharpe should remain secondary until expected-return modeling is validated out of sample.

## Ensemble Portfolio

The recommended default for the Balanced profile should be a robust ensemble rather than the output of one optimizer.

Initial ensemble candidates:

- True HRP;
- Equal Risk Contribution;
- shrinkage Minimum Variance.

A simple first aggregation method is the per-asset median of model weights, followed by normalization and a final constraint projection.

The ensemble must then be evaluated as its own portfolio, including turnover, risk contributions, costs, walk-forward performance, and stress behavior.

## Validation Framework

## Walk-Forward Backtesting

Walk-forward testing should be the primary method-selection mechanism.

A representative default may use:

- 2 to 3 years of training data;
- 1 to 3 months of test data;
- rolling and expanding variants;
- monthly or quarterly re-estimation;
- realistic rebalance rules;
- explicit transaction costs.

Each split must use only information available before its test period.

Required out-of-sample metrics include:

- realized return;
- realized volatility;
- Sharpe and Sortino ratios;
- maximum drawdown;
- drawdown and recovery duration;
- VaR and CVaR;
- turnover;
- estimated transaction costs;
- weight stability;
- concentration stability;
- income and distribution stability;
- worst month and worst quarter.

A method should not be selected because it has the highest in-sample return. Founder should prefer robust median performance, controlled adverse outcomes, stable weights, and low unnecessary turnover.

## Rebalancing Simulation

Founder should simulate:

- monthly rebalancing;
- quarterly rebalancing;
- annual rebalancing;
- threshold-based rebalancing;
- hybrid calendar and threshold rules.

Portfolio drift must be calculated from each instrument's own return:

```text
value_i,t = value_i,t-1 * (1 + return_i,t)
weight_i,t = value_i,t / sum(value_j,t)
```

Using the same portfolio return for every instrument does not model weight drift correctly.

## Return Semantics

Simple and log returns must not be mixed.

For simple returns:

```text
wealth_t = wealth_t-1 * (1 + portfolio_simple_return_t)
```

For log returns:

```text
wealth_t = wealth_t-1 * exp(portfolio_log_return_t)
```

Datasets and schemas must state the return type explicitly. Portfolio backtests should preferably use simple returns for wealth and trade simulation, while log returns may remain useful for selected statistical calculations.

## Costs And Execution Realism

Backtests and transition plans should include:

- broker order fees;
- exchange and external fees;
- bid-ask spread estimates;
- foreign-exchange conversion costs;
- taxes where configurable;
- whole-share rounding;
- cash remainder;
- minimum order size;
- turnover and number of trades.

The trade-preparation layer should consume approved portfolio weights. It must not decide which optimization objective is appropriate.

## Stress And Robustness Analysis

Founder should evaluate portfolios under:

- historical crisis periods;
- equity sell-offs;
- volatility spikes;
- interest-rate shocks;
- currency shocks;
- distribution cuts;
- correlation convergence during stress;
- block-bootstrap return scenarios;
- covariance and parameter perturbations;
- alternate training windows and rebalance schedules.

The report should show how conclusions change when assumptions change.

## Model Comparison And Recommendation

Founder should compare all eligible portfolio candidates using a common scorecard.

The scorecard should include:

- out-of-sample return;
- out-of-sample volatility;
- CVaR;
- maximum drawdown;
- recovery time;
- turnover and costs;
- concentration;
- weight stability;
- income quality where relevant;
- robustness across estimation windows and stress scenarios.

Founder should then produce:

- best defensive candidate;
- best diversified candidate;
- best income candidate;
- best total-return candidate;
- ensemble candidate;
- Equal Weight baseline;
- current portfolio comparison.

The recommendation must include the reason for selection and the material disadvantages of the chosen portfolio.

## Current Technical Prerequisites

Before the optimizer results can be treated as production investment outputs, Founder must address the following points:

1. Correct the log-return and simple-return wealth inconsistency.
2. Correct rebalancing drift to use instrument-level returns.
3. Reject or report invalid prices instead of replacing them with zero returns.
4. Require meaningful minimum observation counts and common-history coverage.
5. Replace large-universe grid-search fallback behavior with production numerical solvers.
6. Replace midpoint-recursive HRP with real hierarchical clustering.
7. Add shrinkage covariance estimators and covariance diagnostics.
8. Make pairwise statistics scalable through partitioning, batching, and filtering.
9. Add complete distribution amount, stability, yield, and NAV-erosion metrics.
10. Incorporate costs, base-currency conversion, and whole-share execution effects.

The existing deterministic implementations should remain useful as test baselines, but they should be labeled clearly and must not be presented as production optimizers.

## Public Access Strategy

The first public version should minimize operating cost and market-data licensing risk.

A suitable progression is:

### Stage 1: Open-source local application

- CLI and local report generation;
- user supplies their own EODHD API key;
- local lake and local portfolio data;
- no public redistribution of provider datasets;
- reproducible example data and mock runs.

### Stage 2: Hosted user interface with bring-your-own-key

- web interface for selections, profiles, analysis, and reports;
- isolated user workspaces;
- user-owned credentials stored securely or used only during the session;
- clear limits and privacy controls;
- no broker execution.

### Stage 3: Managed service

- only after data licensing, security, privacy, legal, and operational requirements are resolved;
- portfolio monitoring and scheduled reports;
- optional broker statement import;
- alerts for drift, distribution cuts, drawdowns, and data quality;
- paid or donation-supported plans.

Founder should initially remain a decision-support and trade-preparation tool. Direct broker order execution should be considered only after the analytical product, audit trail, security model, and regulatory implications are mature.

## Initial Hosted Architecture

The first hosted version should deliberately use a minimal architecture. It should be easy to understand, operate, back up, and replace incrementally.

### Initial topology

```text
Browser / Mobile Browser
          |
          | HTTPS
          v
+-----------------------------+
| Web UI container            |
| Next.js + React             |
| TypeScript + Tailwind       |
| Plotly                      |
| Port 3000                   |
+-------------+---------------+
              |
              | REST / JSON
              v
+-----------------------------+
| API container               |
| FastAPI                     |
| Founder Python Core         |
| SQLite + Parquet access     |
| Port 8000                   |
+-------------+---------------+
              |
              v
       Persistent data volume
```

The initial deployment consists of only:

1. one `web` container;
2. one `api` container containing FastAPI and the Founder analytical package;
3. one persistent data directory or Docker volume.

The first version should not require PostgreSQL, Redis, a separate worker, a message queue, Kubernetes, object storage, or a dedicated authentication service.

### Responsibilities

The Web UI is responsible for:

- responsive desktop, tablet, and mobile presentation;
- portfolio input and editing;
- EODHD key entry for a session;
- analysis configuration;
- Plotly charts and analytical tables;
- displaying progress, warnings, and results.

The API is responsible for:

- validating requests;
- communicating with EODHD using the user's key;
- invoking Founder workflows and analytical functions;
- storing portfolio metadata and analysis-run state;
- writing immutable Parquet result artifacts and JSON manifests;
- returning compact JSON responses to the Web UI.

The Founder Core remains responsible for all financial calculations. Portfolio logic must not be duplicated in the React application.

### Initial data flow

```text
1. User opens Founder.
2. User enters an EODHD key for the current session.
3. User defines a small portfolio, initially approximately 3 to 10 funds.
4. Next.js sends the portfolio and analysis request to FastAPI.
5. FastAPI loads and caches the permitted EODHD data.
6. Founder validates the data and calculates the analysis.
7. The run is stored as Parquet artifacts plus a JSON manifest.
8. SQLite stores the portfolio, positions, run status, and artifact path.
9. FastAPI returns metrics and chart-ready JSON.
10. Plotly renders the analysis in the responsive Web UI.
```

The EODHD key should initially be held only for the active request or session and must never be logged. Persistent encrypted credential storage can be added later.

### Initial storage model

SQLite stores only small application-state records:

```text
portfolios
positions
analysis_runs
settings
```

Analytical outputs remain in Parquet:

```text
data/
  founder.db
  uploads/
  market/
  analytics/
    {run_id}/
      manifest.json
      asset_metrics.parquet
      portfolio_metrics.parquet
      portfolio_returns.parquet
      drawdowns.parquet
      target_weights.parquet
      risk_contributions.parquet
```

SQLite should act as the catalog. Parquet should contain the analytical results. The manifest should record how each result was produced.

### Minimal repository direction

```text
founder/
  apps/
    web/                    # Next.js application
      app/
      components/
      package.json
      Dockerfile
    api/                    # FastAPI application layer
      founder_api/
        main.py
        routes/
        services/
      pyproject.toml
      Dockerfile
  src/
    founder/                # existing analytical core
  data/                     # ignored runtime data
  docker-compose.yml
  pyproject.toml
```

### Minimal API surface

```text
GET  /health

POST /portfolios
GET  /portfolios
GET  /portfolios/{portfolio_id}

POST /analyses
GET  /analyses/{run_id}
GET  /analyses/{run_id}/metrics
GET  /analyses/{run_id}/returns
GET  /analyses/{run_id}/weights
```

For the first small portfolios, FastAPI may execute an analysis synchronously. The API contract should nevertheless expose a run identifier and status so that a separate worker can be introduced without redesigning the Web UI.

### Initial UI scope

The first UI should contain only four main areas:

```text
/dashboard
/portfolio
/analysis/{run_id}
/settings
```

Mobile should emphasize portfolio status, drawdown, risk, income, warnings, and recommended actions. Desktop should additionally expose comparison tables, correlation views, optimizer weights, and larger charts.

Plotly is the initial unified charting library. Responsiveness requires both fluid chart containers and mobile-specific chart layouts; merely shrinking desktop charts is not sufficient.

### Minimal Docker Compose direction

```yaml
services:
  web:
    build:
      context: .
      dockerfile: apps/web/Dockerfile
    ports:
      - "3000:3000"
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
    depends_on:
      - api

  api:
    build:
      context: .
      dockerfile: apps/api/Dockerfile
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: sqlite:////data/founder.db
      FOUNDER_DATA_DIR: /data
    volumes:
      - ./data:/data
```

Production deployment should place HTTPS and a reverse proxy in front of the Web UI and API. An existing NAS reverse proxy may be reused instead of introducing another container.

### Initial analysis scope

The first hosted release should prioritize a small, correct feature set:

1. current user portfolio;
2. Equal Weight benchmark;
3. Inverse Volatility benchmark;
4. Minimum Variance candidate;
5. return and volatility metrics;
6. maximum drawdown;
7. Sharpe and Sortino ratios;
8. CVaR;
9. risk contributions;
10. correlation matrix.

True HRP, production ERC, the Income Optimizer, AI Investment Committee, extensive walk-forward validation, and scheduled monitoring should follow after the base workflow is stable.

### Growth path

The minimal architecture should be extended only when observed load requires it:

```text
SQLite             -> PostgreSQL
local filesystem   -> S3-compatible object storage
synchronous API    -> separate worker and queue
single API         -> multiple API instances
session key        -> encrypted credential vault
```

Each transition should be independent. Parquet result artifacts and stable API contracts should minimize migration cost.

## Proposed Module Direction

```text
founder.risk_model
    sample_covariance
    ledoit_wolf_covariance
    ewma_covariance
    covariance_diagnostics

founder.optimizers
    equal_weight
    inverse_volatility
    minimum_variance
    equal_risk_contribution
    hierarchical_risk_parity
    maximum_diversification
    minimum_cvar

founder.income
    distribution_history
    sustainable_income
    distribution_stability
    nav_erosion
    income_efficiency

founder.backtest
    walk_forward
    rebalance
    transaction_costs
    bootstrap
    stress_scenarios

founder.recommendation
    compare_models
    ensemble_weights
    profile_selection
    explanation

founder.trading
    current_positions
    transition_plan
    flatex_export
```

Existing stable public module surfaces may be preserved while internal package boundaries are introduced incrementally.

## Implementation Priorities

### P0: Correctness and production foundations

1. Merge and stabilize the active quote-fetch workflow.
2. Correct return semantics and portfolio wealth calculations.
3. Correct instrument-level weight drift and rebalancing.
4. Add strict market-data quality and history requirements.
5. Introduce scalable pairwise storage and computation.
6. Add a numerical optimization dependency and production solver boundary.

### P1: Robust portfolio construction

7. Implement Ledoit-Wolf shrinkage covariance.
8. Implement production Minimum Variance.
9. Implement production Equal Risk Contribution.
10. Implement true Hierarchical Risk Parity.
11. Implement Minimum CVaR.
12. Retain Equal Weight, Inverse Volatility, and Maximum Diversification as comparison methods.

### P2: Income specialization

13. Add complete distribution amount and yield metrics.
14. Add distribution stability and cut analysis.
15. Add price return, total return, and NAV-erosion decomposition.
16. Add sustainable net-income and income-efficiency objectives.
17. Add Income-profile constraints and reports.

### P3: Validation and recommendation

18. Expand walk-forward testing across models and risk estimators.
19. Add realistic costs, base-currency effects, and trade rounding.
20. Add stress, bootstrap, and sensitivity analysis.
21. Add ensemble portfolios and a common model scorecard.
22. Generate explainable portfolio recommendations.

### P4: User product

23. Add persisted user portfolio projects and current positions.
24. Add current-versus-target transition analysis.
25. Add structured HTML or web reports.
26. Add a hosted bring-your-own-key interface using the initial two-container architecture.
27. Add portfolio monitoring and alerts after licensing and security review.

## Initial Production Definition Of Done

Founder may describe a portfolio result as a production candidate only when:

- all instruments pass data-quality and minimum-history checks;
- the universe and every input dataset are versioned;
- return semantics are consistent;
- the risk model passes covariance diagnostics;
- the optimizer uses a production solver and reports convergence;
- all constraints are satisfied;
- the candidate is compared with Equal Weight and Inverse Volatility;
- walk-forward results are available;
- costs and turnover are included;
- tail risk and drawdown are reported;
- concentration and risk contributions are reported;
- the recommendation explains important assumptions and disadvantages;
- no result is automatically converted into a broker order without explicit user approval.

## Initial Recommended Default

For the first broadly useful Balanced portfolio, Founder should use:

```text
eligible and quality-controlled universe
  -> Ledoit-Wolf shrinkage risk model
  -> True HRP
  -> Equal Risk Contribution
  -> constrained Minimum Variance
  -> walk-forward comparison after costs
  -> median-weight ensemble
  -> final constraint projection
  -> portfolio evaluation and Flatex trade preparation
```

For the Income profile, the same robust risk framework should be combined with sustainable distribution, NAV-erosion, CVaR, concentration, and turnover constraints.

This combination is the intended strategic direction for Founder: a transparent, reproducible, risk-aware portfolio construction system rather than a single-formula optimizer.
