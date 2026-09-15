# Supported CSV formats

## Shared validation and saving

Cells are checked before dates or numbers are converted. A missing, empty,
or whitespace-only required cell is a row error; missing columns in a
truncated row do not become the text `None`, zero, or fallback values.
Messages identify the affected field in the preview; FX import also exposes
the row and column in the final response. `row_number` starts at 1 for the
first data row, excluding the header. For global parsing errors,
`line_number` instead identifies the line reached by the CSV reader,
including the header and any multiline cells; for bank profiles, it is
relative to the content after the initial skipped rows.

The APIs import valid rows and count invalid ones, with **one commit per
request**. A global error—missing, duplicate, or malformed header,
unreadable CSV structure, or exceeded limits—or an unexpected error rolls
back the entire request. Preview writes no data. The transaction and price
wizards enable confirmation only after a preview with no error rows,
including pages not currently displayed; this interface rule does not
remove API support for partial imports.

## Transactions (Cash Flow → Import CSV)

See specification §8.1. The format is configurable: each profile (table
`csv_import_profiles`, managed under Settings → CSV import templates)
defines its own mapping:

- `delimiter`, `skip_rows`, `date_format`, `decimal_separator`, `default_currency`
- `date_column`, `description_column`, `amount_column` — column names in the CSV header
- `category_column` — **required** for every new profile and every
  preview/import; identifies the file column containing the category name

The name read from `category_column` must match exactly one existing
category **without children**, using the shared key `name.strip().casefold()`:
leading/trailing whitespace and case differences, including Unicode, are
ignored; accents and internal whitespace remain significant. The same rule
applies to category creation and automatic transactions. New names must be
globally unique, including across types and parents.

Legacy categories sharing a name remain readable. When a name matches
multiple records, the row reports the ambiguity with the affected IDs:
no category is chosen by type, parent, or amount sign. Existing records are
not renamed, merged, or reassigned. The name map is built once per import
and is not retained between requests.

A root category is valid if it has no subcategories. A missing column or
empty cell, nonexistent, ambiguous, or non-leaf category, zero amount,
positive amount associated with `expense`, negative amount associated with
`income`, or `transfer` category makes a row unimportable, identically in
preview and import. Categories are never created automatically by CSV
import, and transfers are recorded only through their dedicated workflow.

The mapped description column must appear in the header; its value is
optional, even when missing because the row ends before that column.
Date, amount, and category remain required.

Profiles saved before this rule may still have `category_column = NULL`:
they remain readable and selectable, but the wizard marks them incomplete
and requires a category column at step 3 before continuing. Creating a new
profile without this mapping is rejected. Because no `PUT` update exists,
correcting a legacy profile permanently requires deleting and recreating
it; the system does not invent a mapping for existing data.

**If `default_currency` is not EUR**, an **exchange rate** must also be
provided for all rows in the file: a bank statement is by definition in a
single currency. Without a rate, import is rejected before any row is
written. See [Multiple currencies](multi-currency.md).

Example (a user-created profile with delimiter `;` and comma decimals;
create the example categories before importing):
```
Date;Description;Amount;Category
20/07/2026;Grocery shopping;-45,20;Groceries
21/07/2026;Salary;1800,00;Salary
```

Endpoints: `POST /api/v1/transactions/import/preview` (dry run) and
`POST /api/v1/transactions/import` (multipart/form-data, the same profile
fields + `file` + `account_id`).

**Both require `account_id`**, including preview: duplicate detection
depends on the destination account (see below), so preview cannot answer
without it. In the wizard, the account is selected at step 3 before
producing the preview.

The wizard retains a snapshot of the effective parameters with the preview:
file, profile/mapping, account, currency, and exchange rate. Pagination and
confirmation use that same snapshot. Returning to editing or changing a
parameter invalidates the preview and requires regeneration; a stale
response cannot reactivate it. Relevant controls are locked during requests,
and submitting confirmation twice does not produce another POST. The
backend still revalidates data and duplicates at confirmation: preview does
not reserve or lock database rows.

### When a row is a duplicate

Each imported row has an `import_hash` calculated from **account + date +
amount + description** (`backend/app/utils/deduplication.py`). A row is
skipped and counted in `skipped_duplicates` if that hash already exists
in the database **or** earlier in the same file.

Practical consequences:

- Uploading the same statement twice to the same account does not double
  its balance.
- The same transaction on **different accounts** is imported normally:
  these are two transactions, not a repetition. Previously, the account
  was absent from the hash and the second transaction silently disappeared.
- Two identical rows **within the same file** (two identical charges on the
  same day can occur) are recognized: one is imported. Previously, both
  were accepted and the entire import failed on saving after already
  reporting “2 imported.”
- Amounts are compared at their stored precision of six decimal places:
  `-1.5` and `-1.500000` are the same amount.

Rows with different dates or amounts never collide, so two equal expenses
on different days are both imported. Two identical expenses **on the same
day and account** are indistinguishable, and the second is skipped: if it
is a real transaction, enter it manually with a different description.

Profile endpoints: `GET/POST /api/v1/csv-import-profiles` and
`DELETE /api/v1/csv-import-profiles/{id}`. No `PUT` update is exposed:
correct a profile by deleting and recreating it. A new installation has
no preconfigured categories or import profiles; users create the categories
and mappings relevant to their files.

## Security prices and exchange rates

**Fixed** formats (not configurable; no profile selection), see
specification §5.3. The delimiter is a **semicolon**, not a comma: a comma
column separator would split a comma-decimal price (`17,50`) across two
columns and misalign the row. Decimal values can use either `.` or `,`.

The expected encoding is UTF-8; the Excel BOM is removed automatically.

### Prices — `POST /api/v1/prices/import` (preview: `/api/v1/prices/import/preview`)

```
date;ticker;close;fx_rate
2026-07-20;VWCE;125,10;
2026-07-20;IE00B4L5Y983;125,10;
2026-07-20;AAPL;210,00;0,92
```

- `date` uses ISO `YYYY-MM-DD` format (fixed; does not follow a profile).
- `ticker` accepts either ticker or ISIN: lookup first tries an exact ticker,
  then ISIN.
- `close` is the required quote in the security's currency.
- `fx_rate` is **optional** and needed only for securities quoted in a
  currency other than EUR: it states how many euros one unit of that
  currency is worth on the row's date, and is frozen on the price record
  ([Multiple currencies](multi-currency.md)). For euro securities, leave it
  empty or omit the column entirely: **existing files continue to work
  unchanged**. A foreign security row without an exchange rate is counted
  as an error and skipped, without blocking the rest of the file.
- Structurally and numerically valid rows with an unknown ticker are
  **skipped and counted**: broker exports commonly contain securities the
  user does not track. If the same row also has a malformed date, price,
  or rate, the error takes precedence; it is not classified solely as an
  ignored ticker.
- An existing price for that date is **updated**, not duplicated.

Preview simulates **the whole file in order before extracting the page**,
starting from existing prices. The key is `(security_id, date)`, after
resolving ticker or ISIN: two aliases of the same security therefore share
the same price. Only valid rows update simulated state and **the last valid
row wins**. A later invalid row does not erase the previous valid value.

Counts describe row operations, not the number of distinct final prices:
two valid occurrences without an initial price produce **1 new and 1 update**;
with an initial price, they produce **0 new and 2 updates**. This also
applies to identical rows and duplicates on different pages. Repeated valid
rows show the final row and winning value, including the exchange rate and
EUR equivalent; superseded rows identify their replacement row. In the API
response these fields are `final_row_number`, `final_close`, `final_fx_rate`,
`final_close_eur`, and `superseded_by_row`; they remain `null` where inapplicable.

Confirmation revalidates the file against current state: preview neither
reserves nor locks prices. Upsert with origin `csv_import` retains the
existing ownership rules for imported prices.

### Exchange rates — `POST /api/v1/fx-rates/import`

```
date;from;to;rate
2026-07-20;USD;EUR;0,92
```

If you import `USD;EUR` and the opposite direction does not exist for that
date, the reciprocal (`EUR;USD`) is calculated and inserted automatically.

Date, source currency, destination currency, and rate are required.
Currencies must differ, and the rate and its reciprocal must be positive
and representable. Valid rows are saved even when some rows are invalid.
The response retains `imported`, `reciprocal_calculated`,
`reciprocal_created`, `reciprocal_updated`, and `errors`, and adds
`row_errors`: a list of `{row_number, column, message}` also displayed in
Settings. `column` may be `null` for a whole-row problem. **`errors` counts
invalid rows**: one row with three missing cells contributes one error to
the count and may produce three messages.

FX policy remains distinct from price policy: multiple valid rows for the
same `(date, from, to)`, even identical ones, are **all rejected as duplicate
directions**. Explicit opposite pairs must be consistent within the rate
product tolerance (`0.00000001`). A generated reciprocal
(`csv_import_reciprocal`) is realigned when the direct rate changes; an
explicit opposite rate is not overwritten by the generator and, if
incompatible, prevents import of the new direction.
