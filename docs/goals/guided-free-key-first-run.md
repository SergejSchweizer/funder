# Guided Free-Key First-Run Goal

Last reviewed: 2026-07-17

## Purpose

The first Camovar experience should demonstrate the complete research workflow with a user's own EODHD free key while staying within the provider's limited daily data allowance.

The product should not open with a generic dashboard or a preselected model portfolio. It should guide a new user through the same transparent research sequence used by the Camovar engine:

```text
fetch all available ISIN and listing metadata
  -> apply metadata filters
  -> select a small free-key-compatible research universe
  -> fetch historical quotes for that universe
  -> calculate univariate statistics
  -> apply univariate filters
  -> calculate bivariate statistics
  -> calculate multivariate statistics
  -> construct and compare portfolio candidates
```

The experience should prove that Camovar can reduce a broad investment universe to a small, explainable set of portfolio candidates without presenting a black-box recommendation.

## Product Promise

The opening promise should be simple:

> Turn a broad fund universe into a portfolio you understand.

Camovar should communicate three principles immediately:

- the user supplies their own market-data key;
- every exclusion and selection is reproducible;
- recommendations are based on persisted data and explicit rules, not an unconstrained AI response.

## Primary First-Run Outcome

At the end of the first guided run, the user should understand:

- how many instruments were discovered;
- how metadata eligibility reduced the universe;
- which instruments passed individual data-quality and risk checks;
- which apparently different instruments are statistically redundant;
- how many distinct recent risk groups remain;
- how multivariate structure changes portfolio construction;
- which portfolio candidates were produced and why they differ;
- which conclusions are limited by the short history available through the free key.

A representative final statement is:

```text
Camovar started with the available investment universe,
reduced it through explicit eligibility and statistical checks,
identified the remaining independent risk groups,
and built several portfolio candidates from that evidence.
```

## Guided Funnel

The first-run UI should use a sparse, high-trust design inspired by simple Google and Apple product flows:

- generous whitespace;
- one primary action per screen;
- large, plain-language headings;
- progressive disclosure of technical detail;
- no dense dashboard before the first insight;
- no empty AI chat box as the initial interaction;
- no buy or sell signal language.

The funnel is:

```text
1. Connect EODHD key
2. Select portfolio objective
3. Discover the investment universe
4. Apply metadata eligibility rules
5. Select the free-key research set
6. Prepare market history
7. Calculate univariate statistics
8. Apply univariate filters
9. Calculate bivariate statistics
10. Calculate multivariate statistics
11. Build portfolio candidates
12. Compare, explain, and save the result
```

## 1. Connect Market Data

The first screen should request the user's EODHD key and explain its use clearly.

```text
Connect your market data

[ EODHD API key ]

Camovar shows estimated API usage before each data-fetch step.
The key is not logged and should initially remain session-scoped.

[ Connect ]
```

After validation, Camovar should display the detected access level and the resulting operating mode without overpromising exact capacity.

```text
Connected
Access level: Free
Recommended mode: Guided research set
```

## 2. Select The Objective

The user should choose one primary objective before filtering begins:

```text
Balanced
Defensive
Monthly income
Growth
```

A second compact control may capture the intended portfolio size or risk preference.

Camovar should translate these answers into explicit metadata rules, univariate thresholds, multivariate constraints, and portfolio-comparison priorities.

## 3. Discover The Investment Universe

Camovar fetches and persists the available ISIN and listing metadata.

The UI should summarize the result rather than immediately displaying a large table:

```text
Investment universe discovered

Listings found
Unique ISINs
Preferred or canonical listings
```

The discovery output must be stored as an immutable snapshot with:

- provider;
- retrieval timestamp;
- listing count;
- unique ISIN count;
- canonical-listing count;
- schema version;
- estimated or recorded API usage.

## 4. Metadata Eligibility Filter

The metadata filter removes instruments that cannot satisfy the user's basic objective before historical prices are fetched.

Initial filter dimensions may include:

- fund or ETF type;
- UCITS eligibility where identifiable;
- distributing or accumulating policy;
- distribution frequency where available;
- exchange;
- listing currency;
- product structure;
- leveraged or inverse status;
- supported listing and data availability;
- canonical listing per ISIN.

The result should be shown as a selection waterfall:

```text
all unique instruments
  -> eligible product type
  -> required distribution policy
  -> supported exchanges and currencies
  -> canonical listings
  -> metadata-eligible universe
```

Every excluded instrument should retain a structured exclusion reason.

## 5. Free-Key Research Set

The metadata-filtered universe may still be too large for the free key because univariate analysis requires historical quotes for each instrument.

Camovar therefore needs an explicit free-key research-set step.

The system should estimate the data cost before fetching quotes and produce a small, representative candidate set that fits within the currently available provider allowance.

A guided set should preserve diversity rather than simply select the first records or the highest recent performers. Depending on the objective, it may include representatives from:

- broad global or regional equity;
- defensive or bond exposures;
- income strategies;
- growth or technology exposures;
- alternative diversifiers;
- one benchmark.

The user should be able to accept the Camovar set or manually replace instruments before quote retrieval.

```text
Metadata-eligible instruments: 96
Research capacity for this run: 15

[ Use Camovar selection ]
[ Review and customize ]
```

The exact capacity must be calculated from the current account state and endpoint costs, not hard-coded into the UI.

## 6. Prepare Market History

Historical quote fetching is a separate technical workflow even if it appears as one simple user-facing step.

```text
Preparing market history

Checking available history
Fetching selected instruments
Validating dates and prices
Persisting the market-data snapshot
```

Camovar should fetch data only for the selected research set, persist it locally, and reuse it in all later statistical stages without additional provider calls.

The UI must show:

- estimated calls before execution;
- actual calls after execution;
- instruments completed;
- instruments unavailable;
- common date range;
- observation counts;
- data-quality warnings.

## 7. Univariate Statistics

Camovar evaluates each instrument independently.

The initial free-key-compatible univariate layer should prioritize:

- valid observation count;
- coverage and missing-data diagnostics;
- simple and log returns with explicit semantics;
- annualized return;
- annualized volatility;
- maximum drawdown;
- drawdown duration;
- historical VaR and CVaR;
- Sharpe and Sortino ratios;
- skewness and excess kurtosis;
- recent trend and return stability;
- distribution metrics only where data access and quality allow them.

The user-facing title should remain understandable:

```text
Testing each fund independently
```

The summary should lead with outcomes:

```text
15 instruments analyzed
2 failed data-quality requirements
4 exceeded the selected risk limits
9 remain for relationship analysis
```

## 8. Univariate Filter

The univariate filter removes instruments that are individually unsuitable before pairwise computation begins.

Camovar should provide an objective-specific recommended preset with an advanced customization option.

Possible rules include:

- minimum observation count;
- minimum quote coverage;
- maximum acceptable drawdown;
- maximum CVaR;
- volatility range;
- minimum liquidity proxy where available;
- exclusion of critical data-quality warnings;
- income-specific distribution and NAV-erosion rules when supported.

Each exclusion must retain:

- metric name;
- observed value;
- threshold;
- exclusion reason;
- model and schema version.

## 9. Bivariate Statistics

Camovar next evaluates the relationships between surviving instruments.

The user-facing purpose is:

```text
Finding hidden duplication
```

Required initial measures include:

- Pearson correlation;
- Spearman correlation;
- covariance;
- common observation count;
- common date range;
- optional downside correlation;
- optional stress-period correlation;
- correlation-based distance for clustering.

The principal insight should not be a large unexplained matrix. Camovar should summarize redundancy and groups:

```text
9 individually acceptable instruments
5 distinct recent risk groups
2 highly redundant pairs
```

The UI may then expose:

- a compact heatmap;
- cluster cards;
- the strongest redundant pairs;
- instruments that add the least additional diversification.

Pairwise computation must operate only on the filtered research set and must not create one file per pair.

## 10. Multivariate Statistics

Camovar then evaluates the candidate set as a joint system.

The user-facing purpose is:

```text
Understanding the portfolio structure
```

The initial multivariate layer may include:

- covariance and correlation matrices;
- covariance stability diagnostics;
- hierarchical clustering;
- principal components;
- explained variance;
- effective rank or effective number of independent drivers;
- portfolio volatility;
- portfolio CVaR;
- marginal and percentage risk contributions;
- diversification ratio;
- concentration diagnostics.

A representative insight is:

```text
Although 9 instruments remain,
4 common components explain most recent portfolio movement.
```

The UI should explain this as a diversification finding rather than requiring the user to understand eigenvalues first.

## 11. Portfolio Candidates

The first guided run should produce several alternatives under the same dataset and constraints.

At minimum:

- Equal Weight baseline;
- Inverse Volatility baseline;
- constrained Minimum Variance candidate;
- a diversified candidate using the best production-ready multivariate method available;
- an objective-specific candidate when the required model is production-ready.

The result page should compare a small number of metrics:

- instrument count;
- recent return;
- volatility;
- maximum drawdown;
- CVaR;
- concentration;
- largest risk contribution;
- turnover from an existing portfolio where relevant.

Every metric must clearly state that it is based on the available historical window and is not a forecast.

## 12. First Impressive Insight

The first result screen should not begin with a dense dashboard.

It should begin with one plain-language conclusion derived from the stored statistics, for example:

```text
Camovar found that the surviving funds represent
fewer independent risk sources than their number suggests.
```

Supporting figures may include:

```text
Initial unique ISINs
Metadata-eligible instruments
Instruments statistically analyzed
Univariate survivors
Distinct risk groups
Portfolio candidates
```

The next screen should explain the strongest redundancy, the dominant portfolio risk driver, and the smallest change between competing portfolio candidates.

## AI Role

AI should be introduced only after Camovar has persisted deterministic analysis results.

Its responsibilities are:

- explain why an instrument was excluded;
- explain why two funds are considered redundant;
- describe the difference between capital weight and risk contribution;
- explain trade-offs between portfolio candidates;
- translate statistical limitations into understandable language;
- answer questions using the current run artifacts and manifest.

AI must not invent metrics, select uncomputed assets, or generate unconstrained weights independently of the analytical engine.

Recommended first questions are:

```text
Why were these funds excluded?
Which funds add the least diversification?
Why does this fund contribute more risk than its weight?
What do I give up with the defensive portfolio?
How reliable is this result with the available history?
```

## Persistence And Resumability

The guided workflow must be resumable because free-key limits may prevent all data-fetch operations from being completed in one session.

Each stage should create a persisted artifact and stable identifier:

```text
universe_snapshot_id
metadata_selection_id
research_set_id
market_snapshot_id
univariate_run_id
univariate_selection_id
bivariate_run_id
multivariate_run_id
portfolio_run_id
```

Statistical stages should reuse persisted market data and consume no additional provider calls unless the user explicitly refreshes the dataset.

The UI should show the pipeline state:

```text
Universe              complete
Metadata filter       complete
Market history        complete
Univariate analysis   complete
Univariate filter     complete
Relationships         in progress
Portfolio structure   pending
Portfolio candidates  pending
```

## Call-Budget Rules

Camovar must treat provider capacity as an explicit resource.

Before every external data-fetch operation it should show:

- estimated calls;
- available calls where detectable;
- instruments covered;
- instruments deferred;
- whether cached data can be reused.

The system should never silently exceed the estimated scope or start fetching history for the full metadata universe.

Statistical recomputation from persisted data should be clearly marked as requiring no new market-data calls.

## Trust And Limitations

The free-key experience must explicitly distinguish what can and cannot be inferred from the available history.

Camovar may provide useful recent evidence about:

- data quality;
- recent volatility;
- recent correlations;
- recent drawdowns;
- current concentration;
- recent portfolio risk contributions.

Camovar must warn that limited history does not robustly establish:

- long-term crisis behavior;
- stability across multiple market regimes;
- long-term distribution sustainability;
- reliable expected returns;
- durable optimizer superiority.

The limitation panel should be visible, concise, and attached to the recommendation rather than hidden in legal text.

## Visual Design Goal

The detailed interface, layout, motion, visualization, and responsive design requirements are defined in:

```text
docs/goals/visual-research-funnel.md
```

The visual goal is part of the first-run product requirement, not optional decoration. The research funnel should preserve the same analytical sequence while presenting one understandable question, visualization, insight, and action at a time.

## Design Principles

The first-run experience should follow these rules:

1. One main decision per screen.
2. Plain-language title first, technical term second.
3. Show reductions as a waterfall or funnel.
4. Show one important insight before detailed charts.
5. Reveal tables and advanced metrics only on demand.
6. Explain every exclusion and recommendation.
7. Never represent a one-year result as a long-term forecast.
8. Persist every stage so the user can resume without repeating work.
9. Keep the same workflow when the user later upgrades to a larger data plan.
10. Use the free-key restriction as a transparent research boundary, not an artificial engagement mechanism.

## Success Criteria

The guided first run is successful when a new user can complete the workflow without understanding the internal module names and can accurately explain:

- how the initial universe was reduced;
- why the final instruments survived;
- which instruments were redundant;
- how many recent risk groups remain;
- why the portfolio candidates differ;
- what the available data cannot prove.

The first run should create enough value that the user saves the project and returns to refresh data, test another objective, widen the research universe, or continue with a larger EODHD plan.
