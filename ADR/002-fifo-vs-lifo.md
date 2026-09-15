# ADR 002: FIFO method for calculating security cost basis

**Status:** Accepted as an internal convention, not a tax convention  
**Last reviewed:** 2026-09-11

## Context
Calculating the cost of securities sold and the remaining cost basis of
portfolio positions requires a method for matching purchases and sales
(see specification §5.2, §9.1).

## Decision
Adopt FIFO (First In, First Out) as the internal convention for matching
purchases and sales in PFIM portfolio calculations.

Lot matching for cost, P&L, and the tax register remains global per security
(`security_id`). Share availability is also checked per securities account
and security: a new sale or purchase deletion cannot leave negative running
quantities in that securities account, even if another holds enough shares.
Ordering is `(date, id)` and includes subsequent and future transactions.

This clarification corresponds to requirement A03. It introduces neither
security transfers nor tax FIFO per securities account, and does not
reassign historical transactions. Inconsistent legacy sequences remain
readable; new sales and purchase deletions are rejected with details of the
first deficit. Transactions that increase availability retain the existing
protections.

Under A08, security deactivation uses availability per securities account
as of today, including today's trades: it requires zero quantity in every
securities account and no historical running deficit. A zero global balance
does not offset opposite securities-account balances. Future trades and
income with future payment dates are separate blockers, even when future
transactions offset each other or income has a zero net amount. Future
quotes and security maturity dates alone do not block deactivation;
reactivation retains its ordinary path. The check returns a conflict with
securities accounts, sources, and dates, without correcting legacy data.

For trailing 365-day KPIs (A13), the EUR FIFO cost of open positions uses the
same `as_of` date as the income numerator, excluding future trades. The
income window is `[as_of − 364 days, as_of]` and remains independent of the
Income Analysis period filters. This clarification aligns the time cutoff
without changing global lot matching.

## Rationale
- Deterministic, straightforward to explain and verify against alternative
  methods (LIFO and weighted average cost)
- Preserves continuity of the calculations and tests already in the Finance Engine

This decision does not claim tax compliance. In Italy, the applicable
method, instrument, and tax regime must be checked separately; the TUIR also
includes LIFO presumptions for specific cases. Official references:
[TUIR, article 67](https://www.normattiva.it/uri-res/N2Ls?urn%3Anir%3Apresidente.repubblica%3Adecreto%3A1986-12-22%3B917~art67-com1-letm=)
and [Italian Revenue Agency, Schedule RT](https://infoprecompilata.agenziaentrate.gov.it/portale/web/guest/quadro-rt).

## Consequences
- The Finance Engine implements a chronological queue of purchase lots
  (see `backend/app/finance/portfolio.py`).
- Valuations, P&L, and tax estimates that depend on FIFO matching must be
  presented as informational, not as a tax-recognized cost basis.
- Supporting other methods in the future will require a pluggable strategy
  without breaking the public interface.
