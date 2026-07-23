# Visual Research Funnel Goal

Last reviewed: 2026-07-17

## Purpose

Camovar should present its quantitative research pipeline through a professional, calm, and highly focused interface. The visual direction should take inspiration from the clarity of Google product entry points and the hierarchy, spacing, typography, and interaction discipline associated with Apple product experiences.

The interface must not resemble a dense trading terminal during onboarding. It should guide the user from a broad investment universe to a small set of explainable portfolio candidates through one understandable decision or insight at a time.

This document complements `guided-free-key-first-run.md`. That document defines the functional research sequence. This document defines how the sequence should be presented visually.

## Core Experience

Camovar should feel like a guided research workspace rather than a generic portfolio dashboard.

Each screen should contain:

1. one central question;
2. one primary visualization;
3. one main Camovar insight;
4. one primary action;
5. optional detail available through progressive disclosure.

The user-facing transformation is:

```text
many available instruments
  -> relevant instruments
  -> individually suitable instruments
  -> distinct risk groups
  -> portfolio structures
  -> explainable portfolio candidates
```

The technical pipeline remains:

```text
ISIN and listing discovery
  -> metadata filtering
  -> free-key research-set selection
  -> market-history preparation
  -> univariate statistics
  -> univariate filtering
  -> bivariate statistics
  -> multivariate statistics
  -> portfolio construction and comparison
```

## Four Visual Macro Phases

The twelve technical steps should be grouped into four user-facing phases:

```text
UNIVERSE
  Discover instruments
  Apply metadata eligibility
  Select the research set

QUALITY
  Prepare market history
  Analyze each fund
  Apply data-quality and risk rules

RELATIONSHIPS
  Compare surviving funds
  Find duplication and risk groups

PORTFOLIO
  Understand the combined structure
  Build and compare portfolio candidates
```

The user should always understand which phase is active, which phases are complete, and which phase comes next.

## Persistent Funnel Indicator

The primary recurring visual motif should be a shrinking research universe.

Example:

```text
3,104 funds
     |
   96 eligible
     |
   15 analyzed
     |
    8 survivors
     |
    5 risk groups
     |
    4 portfolios
```

A compact version should remain visible during the full process:

```text
Universe 3,104 -> Eligible 96 -> Analyzed 15 -> Distinct 5 -> Portfolios 4
```

The active stage is emphasized. Completed stages are quiet but visible. Future stages are muted.

The same visual objects should transform during the journey:

1. many points represent the discovered universe;
2. excluded points fade during metadata filtering;
3. the research set moves into a risk-return space;
4. unsuitable points fade after univariate filtering;
5. related points move into clusters during bivariate analysis;
6. selected clusters become portfolio building blocks;
7. building blocks resolve into portfolio candidate cards.

This continuity should make the pipeline feel like one research story rather than a collection of unrelated pages.

## Public Landing Page

The public landing page should be sparse.

```text
CAMOVAR

From thousands of funds
to a portfolio you understand.

Camovar filters, analyzes, and combines investment funds
through a transparent quantitative research process.

[ Start with my EODHD key ]

View an example
```

Only three supporting promises should appear near the primary call to action:

```text
Transparent selection
Every excluded fund has a reason.

Quantitative analysis
Risk, diversification, and portfolio structure.

No black box
Every result can be reproduced.
```

The landing page should avoid:

- live market tickers;
- market-news feeds;
- dense feature grids;
- multiple competing primary buttons;
- stock-photo imagery;
- an empty AI chat box;
- a prebuilt model portfolio presented as a recommendation.

## Research Workspace Layout

### Desktop

During the guided first run, the page should use a centered research canvas without a permanent application sidebar.

```text
+------------------------------------------------------------------+
| Camovar     Research: Monthly Income      Data calls 8/20    User |
+------------------------------------------------------------------+
| Universe       Quality       Relationships       Portfolio        |
|    complete       active          pending           pending       |
+------------------------------------------------------------------+
|                                                                  |
|                    CENTRAL QUESTION                              |
|                                                                  |
|                  Primary visualization                           |
|                                                                  |
|                  Camovar Insight                                 |
|                                                                  |
|                    [ Primary action ]                             |
|                                                                  |
+------------------------------------------------------------------+
| Details | Exclusions | Data quality | Advanced methodology       |
+------------------------------------------------------------------+
```

A normal workspace navigation should appear only after the first project has been completed or saved:

```text
Dashboard
Research
Portfolios
Analyses
Data
Settings
```

### Mobile

Mobile should preserve the same research sequence, but show only one primary visualization at a time.

```text
Camovar                                      8/20

Step 5 of 10
Understanding each fund

Progress
-------------------------------------

Primary visualization

Camovar Insight

[ Continue ]
```

Mobile behavior should use:

- full-width cards;
- bottom sheets for detail;
- a persistent bottom primary action where appropriate;
- horizontal scrolling only for intentionally compact comparisons;
- no desktop tables compressed into a narrow viewport.

## Screen Hierarchy

Each research screen should use the same hierarchy:

```text
Eyebrow:       phase and technical context
Heading:       plain-language question or conclusion
Supporting:    one or two concise sentences
Visualization: one primary analytical representation
Insight:       the most important interpretation
Action:        one primary next step
Details:       optional expandable methodology and tables
```

Example:

```text
RELATIONSHIPS · Bivariate analysis

Which funds are telling the same story?

Camovar compares the surviving instruments to identify hidden
duplication and genuinely different recent risk behavior.

[ Cluster map ]

Camovar Insight
Eight suitable funds form only five distinct risk groups.

[ Continue to portfolio structure ]
```

## Connect Market Data Screen

```text
Connect your market data

Camovar uses your EODHD key for your personal research project.

[ EODHD API key                                      ]

Not included in reports
Never written to application logs
May remain limited to this session

[ Connect ]
```

After connection:

```text
Free access connected

Available history: limited
Operating mode: Guided research set
Data calls used today: 0

Camovar will estimate usage before every external data request.
```

The data-call indicator should be informative rather than alarming.

## Select Objective Screen

The first run should ask only one main objective question:

```text
What should this portfolio achieve?

[ Preserve capital ]
[ Balanced growth  ]
[ Monthly income   ]
[ Maximum growth   ]
```

A second compact question may capture intended portfolio size:

```text
How many funds should the final portfolio contain?

[ 3-5 ]   [ 5-8 ]   [ 8-12 ]
```

All advanced constraints should remain collapsed under a secondary action.

## Universe Discovery Screen

User-facing heading:

```text
What can Camovar invest in?
```

The discovery animation should show the universe forming without exposing implementation logs.

```text
Discovering listed instruments

Listings found
Unique ISINs
Canonical listings
```

The completed state should emphasize that the snapshot is reusable:

```text
Your investment universe is ready

3,104 unique instruments
1,759 canonical listings

Snapshot saved
Can be reused without another provider request

[ Define eligibility ]
```

## Metadata Filter Screen

The interface should present understandable selection cards rather than a database-style filter form.

```text
Which funds belong in this research universe?

Product type        UCITS ETFs
Distribution        Monthly distributing
Regions             Global, Europe, USA
Currencies          EUR and USD
Structures          Exclude leveraged and inverse

[ Apply Camovar recommendation ]
```

The primary visualization should be a selection waterfall:

```text
3,104 unique instruments
|
|-- duplicate or secondary listings
|-- unsuitable distribution policy
|-- unsupported market or currency
|-- unsuitable product structure
|
96 metadata-eligible funds
```

Each exclusion category should be selectable and should explain the rule in plain language.

## Free-Key Research Set Screen

When the eligible universe exceeds the available data capacity, the interface should turn the limitation into a transparent research boundary.

```text
96 funds match your rules

Your current data access can deeply analyze
15 instruments in this run.

[ Use a representative Camovar set ]
[ Select the instruments manually ]
```

The representative set should be summarized by role:

```text
4 broad equity
3 income
3 defensive
2 growth
2 alternative diversifiers
1 benchmark
```

The screen must state:

```text
This is a research sample, not the final portfolio.
```

## Market History Screen

```text
Preparing market history

15 historical series
Estimated external calls: 15
Available range: limited by the connected account

[ Load market history ]
```

During execution:

```text
11 of 15 instruments loaded

Validating dates
Checking missing observations
Persisting the data snapshot
```

Unavailable instruments should receive a specific explanation and a replacement action.

## Univariate Analysis Screen

User-facing heading:

```text
Understanding each fund
```

Secondary technical label:

```text
Individual fund analysis · Univariate statistics
```

The primary visualization should be a risk-return scatterplot:

- x-axis: annualized volatility;
- y-axis: recent annualized return;
- point size: maximum drawdown magnitude;
- optional ring or opacity: data quality and coverage.

Selecting a point should reveal a compact detail card:

```text
Fund A

Return               14.2%
Volatility           18.5%
Maximum drawdown    -16.1%
CVaR                  -2.9%
Observations            247

Data confidence: Limited
```

Only one interpretation should be emphasized below the chart:

```text
Camovar Insight

The highest-yield instruments also show the weakest
recent capital preservation.
```

Detailed metric tables remain optional.

## Univariate Filter Screen

```text
Which funds are individually suitable
for deeper portfolio analysis?
```

The recommended quality filter should be visible as a coherent preset:

```text
Sufficient observations
Required quote coverage
No critical price-quality failure
Drawdown inside the selected tolerance
Tail risk inside the selected tolerance

[ Apply quality filter ]
```

The reduction should update live:

```text
15 analyzed
  -> 11 pass data quality
  -> 9 pass risk limits
  -> 8 remain
```

Every excluded instrument should receive an evidence card:

```text
Excluded: Fund D

Maximum drawdown       -38.4%
Selected limit         -25.0%

This instrument does not satisfy the selected recent-loss rule.
```

Camovar should describe the fund as incompatible with the chosen rules, not universally bad.

## Bivariate Analysis Screen

User-facing heading:

```text
Finding hidden duplication
```

Secondary technical label:

```text
Pairwise relationship analysis · Bivariate statistics
```

The primary visualization should be a cluster map rather than a full matrix.

```text
Global equity cluster        Income cluster
      o--o--o                    o--o

Defensive cluster             Alternative
      o--o                        o
```

A concise result should lead:

```text
8 individually suitable funds
form only 5 distinct recent risk groups.
```

A redundancy card should explain the strongest pair:

```text
Potential duplication

Fund A <-> Fund B

Correlation                 0.94
Downside correlation        0.91
Common observations          246

Holding both is unlikely to add substantial recent diversification.
```

The correlation heatmap should remain available under a detail view.

## Multivariate Analysis Screen

User-facing heading:

```text
Understanding the combined system
```

Secondary technical label:

```text
Portfolio structure · Multivariate statistics
```

The screen should explain the candidate universe as a joint system.

Primary summaries may include:

```text
8 candidate funds
5 risk clusters
4 dominant portfolio drivers
```

A factor or component view may show:

```text
Global equity driver       41%
Technology/growth driver   21%
Income/options driver      16%
Rates/defensive driver     13%
Independent effects         9%
```

A risk-contribution comparison should demonstrate why equal capital weights do not imply equal risk:

```text
                 Capital weight     Risk contribution
Fund A                12.5%               24.1%
Fund B                12.5%               18.3%
Fund C                12.5%                7.4%
```

The user should not need to understand eigenvalues before understanding the diversification conclusion.

## Portfolio Candidate Screen

Camovar should display three or four large portfolio cards rather than a large optimizer table.

Initial categories:

```text
SIMPLE
Equal Weight
Transparent baseline

DEFENSIVE
Minimum Risk
Lowest recent risk

DIVERSIFIED
Balanced Risk
Broadest estimated risk spread

YOUR OBJECTIVE
Income or Growth
Objective-specific trade-off
```

Each card should initially expose only:

- number of funds;
- recent return;
- volatility;
- maximum drawdown;
- CVaR;
- largest risk contribution;
- one-line explanation.

The quantitative method should appear as secondary methodology, not as the primary card title.

## Final Camovar Moment

The completed research project should summarize the full transformation:

```text
Camovar Research Complete

3,104  unique instruments discovered
96     matched the metadata rules
15     received market-data analysis
8      passed individual quality and risk rules
5      distinct recent risk groups were identified
4      portfolio alternatives were constructed
```

The primary final conclusion should be specific and evidence-based:

```text
The diversified candidate uses six funds
from five different recent risk groups.

No single fund contributes more than
23% of estimated portfolio risk.
```

Primary actions:

```text
[ Compare portfolios ]
[ Save research project ]
```

Secondary action:

```text
Download methodology report
```

## AI Presentation

AI should not be introduced as an empty chat surface.

It should appear after deterministic analysis as contextual assistance under labels such as:

```text
Camovar Insight
Research Assistant
```

Suggested questions should be generated from the current screen:

```text
Why was this fund excluded?
Why are these funds considered duplicates?
Which portfolio has the lowest estimated tail risk?
What is sacrificed in the defensive portfolio?
How reliable is the result with the available history?
```

AI responses must cite the current run's persisted metrics, exclusions, model outputs, and limitations.

## Visual Design System

### Color

The interface should use a neutral base with one primary Camovar accent.

```text
Background          #F7F7F5
Surface             #FFFFFF
Primary text        #111111
Secondary text      #6B6B70
Border               #E5E5E3
Camovar accent      #315EFB
Positive            #16855B
Caution             #B7791F
Critical            #C63C3C
```

Green and red are semantic states, not decorative theme colors.

### Typography

Recommended scale:

```text
Hero                 56-64 px
Page title           36-44 px
Section title        24-28 px
Card title           18-20 px
Body                 15-17 px
Metric number        28-40 px
```

Recommended font stack:

```css
font-family: Inter, Geist, ui-sans-serif, system-ui, sans-serif;
font-variant-numeric: tabular-nums;
```

Tabular numbers should be used for metrics so values remain visually stable when updated.

### Spacing

Camovar should use a consistent eight-pixel spacing system:

```text
8    compact spacing
16   control spacing
24   card spacing
32   section spacing
48   major section separation
64   page separation
96   hero separation
```

### Cards And Surfaces

Cards should use:

- 16 to 20 pixel corner radius;
- a thin neutral border;
- minimal shadow;
- white or near-white surfaces;
- no decorative gradients by default;
- no permanent glass-effect panels.

Visual depth should emphasize navigation, dialogs, and primary interactive surfaces rather than every metric.

### Controls

Controls should be:

- large enough for touch use;
- visually quiet in their default state;
- explicit in selected state;
- keyboard accessible;
- accompanied by visible focus states;
- phrased as decisions rather than technical configuration where possible.

## Motion System

Motion should explain the research transformation.

Recommended uses:

- instruments appear during universe discovery;
- excluded instruments fade during filtering;
- surviving points reposition into the risk-return chart;
- similar funds move together during clustering;
- risk groups transform into portfolio building blocks;
- building blocks resolve into candidate cards;
- metric changes animate without causing layout shifts.

Recommended timing:

```text
Small interaction             150-200 ms
Page transition               250-350 ms
Research transformation       500-800 ms
```

Avoid:

- continuously moving market tickers;
- bouncing buttons;
- decorative particle effects;
- dramatic three-dimensional transitions;
- animation without analytical meaning.

Reduced-motion preferences must be respected.

## Visualization Responsibilities

Use normal React components and SVG for the narrative funnel:

- universe points;
- reduction waterfall;
- pipeline progress;
- cluster map;
- transformation between stages.

Use Plotly for analytical charts:

- risk-return scatterplots;
- return and drawdown time series;
- correlation heatmaps;
- risk contribution charts;
- portfolio comparisons;
- scenario and backtest results.

Use Framer Motion or an equivalent lightweight motion layer for state transitions and transformation animation.

Do not use Plotly as the general page-layout or funnel-animation framework.

## Progressive Disclosure

The first layer should show only:

- the question;
- the result;
- the most important visual evidence;
- the next action.

A second layer may show:

- fund-level detail;
- exclusion reasons;
- metric definitions;
- data-quality warnings;
- methodology.

A third advanced layer may show:

- full tables;
- covariance and correlation matrices;
- PCA details;
- optimizer diagnostics;
- schema and run metadata.

The user should never be required to inspect the advanced layer to complete the first run.

## Accessibility And Responsiveness

The interface should support:

- keyboard navigation;
- visible focus states;
- sufficient contrast;
- text alternatives for visual insights;
- non-color indicators for status;
- reduced motion;
- chart summaries for screen readers;
- touch targets suitable for mobile interaction.

Responsive design should change information hierarchy, not merely shrink desktop layouts.

Desktop emphasizes:

- comparison;
- larger visualizations;
- methodology and detail;
- side-by-side portfolio candidates.

Mobile emphasizes:

- current stage;
- one key insight;
- one visualization;
- warnings;
- the next decision.

## Non-Goals

The guided Camovar interface should not initially become:

- a real-time trading terminal;
- a social investment feed;
- a market-news portal;
- a universal ETF screener with thousands of visible rows;
- a chatbot that replaces the research pipeline;
- a visually dense professional terminal clone;
- an interface that hides methodology behind a proprietary score.

## Design Acceptance Criteria

The visual research funnel is successful when:

1. a new user always knows the current research phase;
2. each screen has one obvious primary action;
3. the reduction from the universe to portfolio candidates remains visible;
4. plain-language conclusions appear before technical terminology;
5. no essential step requires reading a dense table;
6. every exclusion and recommendation can be opened and explained;
7. desktop and mobile preserve the same research meaning with different layouts;
8. animation clarifies data transformation rather than decorating the page;
9. AI appears only after deterministic analysis exists;
10. the final screen clearly communicates what Camovar discovered, removed, grouped, and constructed.

The intended experience combines:

```text
Google-like clarity of entry
  + Apple-like hierarchy and interaction discipline
  + Camovar's transparent quantitative transformation
```

The defining design rule is:

> A screen should not show everything Camovar calculated. It should show exactly what the user must understand or decide next.
