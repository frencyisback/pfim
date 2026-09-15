# ADR 003: No real-time bank or broker integration in v1.0

**Status:** Accepted  
**Last reviewed:** 2026-08-17

## Context
Prices and bank transactions could theoretically be synchronized through
broker or banking APIs.

## Decision
v1.0 uses only manual, configurable CSV imports for transactions, prices,
and exchange rates (see specification §1.3, §8).

## Rationale
- Avoids the complexity and cost of OAuth authentication and paid bank/broker APIs
- Keeps the application core and database local
- Profile-based CSV imports cover most practical cases

## Consequences
- Users must manually export CSV files from their bank or broker
- Real-time integration remains possible in v2.0 as an additional module
  without affecting the current architecture (the Finance Engine is
  independent of the data source)
