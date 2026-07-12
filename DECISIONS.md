# Decisions

Last reviewed: 2026-07-12

Record durable technical decisions here. Use short entries with context, decision, consequences, and update triggers.

## D001. Keep Local Secrets Out of Git

Date: 2026-07-12

Context: The project needs local API credentials for EODHD EOD historical data.

Decision: Store local credentials in ignored environment files such as `.env.local`. Track only examples or documentation, never real tokens.

Consequences: Any code that needs credentials should read from environment variables or local config loaders. `.gitignore` must continue excluding `.env` and `.env.*` while allowing `.env.example`.

Update trigger: Revisit if the project adopts a dedicated secret manager, encrypted local config, or deployment-specific credential flow.

## D002. Track Architecture, Risks, Backlog, and Decisions as First-Class Docs

Date: 2026-07-12

Context: The workspace needs persistent project memory that survives coding sessions and gives future changes a review checklist.

Decision: Maintain `ARCHITECTURE.md`, `RISKS.md`, `BACKLOG.md`, and `DECISIONS.md` at the repository root and stage them in Git.

Consequences: Changes that affect architecture, risk, planned work, or durable technical direction must update the corresponding document in the same change.

Update trigger: Revisit if these docs move into generated documentation or a different project governance system.

## D003. Use EODHD as the First ETF Quote Source

Date: 2026-07-12

Context: The project goal is to analyze end-of-day quotes for multiple thousands of ETFs and build minimum-risk portfolio weights.

Decision: Use EODHD EOD Historical Data as the first data source for ETF discovery and quote ingestion. Use exchange symbol-list enumeration for broad universe discovery because the Search API is capped at 500 results.

Consequences: Discovery code must handle multiple exchanges, duplicate listings, ETF and fund type filters, and token-free outputs. Quote ingestion must validate coverage before optimization consumes the data.

Update trigger: Revisit if another provider becomes primary, EODHD endpoint behavior changes, or the universe definition moves away from ETF/fund instruments.

## D004. Start With Minimum-Risk Portfolio Optimization

Date: 2026-07-12

Context: The first product goal is optimal portfolio weighting based on minimal risk.

Decision: Start with minimum-variance portfolio optimization over validated ETF return histories, then add constraints explicitly as project requirements mature.

Consequences: The implementation needs clean return series, covariance estimation, duplicate instrument handling, and documented constraints before weights are trusted.

Update trigger: Revisit if the objective changes to risk parity, target return, maximum Sharpe ratio, drawdown minimization, or multi-objective optimization.

## D005. Deduplicate ETF Universe By ISIN And Prefer XETRA

Date: 2026-07-12

Context: The `UCITS ETF` discovery set contains duplicate listings across exchanges. Portfolio construction should not overweight the same fund because one ISIN appears on multiple venues.

Decision: Use one canonical listing per non-empty ISIN for quote fetching and optimization. Prefer the `XETRA` listing when the ISIN is available on XETRA; otherwise select a fallback exchange deterministically from the remaining listings.

Consequences: Fetch planning should target `docs/eodhd_ucits_etf_canonical_isins.csv`, not the raw listing discovery file. Rows without ISIN require a separate review before they can enter the optimization universe.

Update trigger: Revisit if the preferred exchange changes, a primary-listing signal becomes available, or optimization needs multiple currency/listing variants of the same ISIN.

## D006. Use EODHD For Data And Flatex For Trading

Date: 2026-07-12

Context: Funder needs a clear separation between market data sourcing and trade execution assumptions.

Decision: Use the EODHD subscription as the main source for EOD Historical Data and Flatex as the intended trading exchange/broker venue for ETF trades.

Consequences: Data ingestion should be designed around EODHD symbols, exchanges, and API limits. Portfolio output should include enough listing, currency, and exchange metadata to support later Flatex trade preparation.

Update trigger: Revisit if the market data subscription changes, Flatex is replaced, or execution constraints require a different canonical listing selection rule.

## Update Rules

Add or update a decision when:

- A choice changes data contracts, external APIs, deployment, storage, or quality gates.
- A decision explains why a non-obvious approach was selected.
- A previous decision is replaced or retired.

Do not rewrite old decisions silently. Add a superseding entry and mark the old decision as superseded.