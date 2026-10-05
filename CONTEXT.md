# Invoice Intelligence — the pipeline

The flow in one line: drop it, extract it, standardize it, review it, query it.

| Stage | Job | Input | Output | Human check |
|---|---|---|---|---|
| `01_inbox` | receive raw invoices | user drops PDFs, or `inbox_path` in `_shared/settings.md` | the PDFs (never modified) | — |
| `02_extracted` | extract, then standardize | an inbox PDF + the matching `_templates/` file + `_shared/` | one `.md` per document | clear every `needs_review: true` |
| `03_data` | index for numbers + matching checks | approved records in 02 | `invoices.db`, `exceptions.md` | read the exceptions |
| `04_graph` | index for relationships | approved records in 02 | `triples.csv` | — |

Factory (stable, every run): `_shared/`, `_templates/`, `_system/`
Product (new each run): `02_extracted/*.md`; 03 and 04 are rebuilt from it and can be deleted anytime.

Status is whatever exists:
- an inbox file with no record in 02 → not extracted
- a record with `needs_review: true` → waiting on a person
- a record with `needs_review: false` → in the database

## Schema (fixed — change it here and in the scripts together)
Every document is unique by (vendor, number). Join on BOTH.

invoices(invoice_no, vendor, vendor_raw, doc_type, client, date, due_date, total, currency, po_no, file)
line_items(vendor, invoice_no, description, qty, unit_price, amount, gl_account)        → invoices
purchase_orders(po_no, vendor, vendor_raw, client, date, total, currency, file)
po_lines(vendor, po_no, description, qty, unit_price, amount, gl_account)               → purchase_orders
payments(payment_id, vendor, vendor_raw, client, date, amount, method, currency, file)
payment_applications(vendor, payment_id, invoice_no, amount)                            → payments
contracts(contract_id, vendor, vendor_raw, client, title, contract_type, effective_date, end_date, auto_renew,
          renewal_term, notice_days, notice_deadline, payment_terms, billing_frequency, recurring_amount, total_value, currency, file)
contract_terms(vendor, contract_id, term, value, section)                               → contracts
contract_rates(vendor, contract_id, description, unit_price, unit)                      → contracts
invoice_balances (view): vendor, invoice_no, total, paid, open_balance, status (open | partial | paid | overpaid)
ap_aging (view): unpaid invoices with days_past_due and bucket (current | 1-30 | 31-60 | 61-90 | 90+)
po_status (view): vendor, po_no, ordered, billed, remaining, status (open | partly billed | fully billed | over-billed)
records: every loaded document (type, vendor, number, vendor_raw, date, amount, human_approved, source_file)
review_queue · refused_duplicates · exceptions(kind, detail) · deadlines(status, days_left) · settings(as_of)

Links: invoice.po_no → purchase_orders · payment_applications.invoice_no → invoices ·
       invoice → contract when the vendor matches and the invoice date is inside the contract term
Broken or suspicious links are listed in `03_data/exceptions.md` (they never block loading).

## Done means
A dropped document becomes a reviewed record, appears in the database, and can be answered about. Nothing more.
