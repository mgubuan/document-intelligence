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

invoices(invoice_no, vendor, vendor_raw, doc_type, client, date, due_date, total, currency, po_no,
         service_start, service_end, posting_period, tax_amount, tax_type, freight, fx_rate, functional_amount,
         discount_pct, discount_days, department, class, location, project, entity, file)
         posting_period defaults to the service_end month, else the invoice month
line_items(vendor, invoice_no, description, qty, unit_price, amount, gl_account, gl_number, functional_amount,
           department, class, location, project, entity)                                 → invoices
purchase_orders(po_no, vendor, vendor_raw, client, date, total, currency, receipt_required, file)
po_lines(vendor, po_no, description, qty, unit_price, amount, gl_account)               → purchase_orders
receipts(receipt_id, vendor, po_no, date, file) · receipt_lines(vendor, receipt_id, description, qty_received) → purchase_orders
payments(payment_id, vendor, vendor_raw, client, date, amount, method, currency, fx_rate, functional_amount, void, file)
payment_applications(vendor, payment_id, invoice_no, amount)                            → payments
contracts(contract_id, vendor, vendor_raw, client, title, contract_type, effective_date, end_date, auto_renew,
          renewal_term, notice_days, notice_deadline, payment_terms, billing_frequency, recurring_amount, total_value, currency, file)
contract_terms(vendor, contract_id, term, value, section)                               → contracts
contract_rates(vendor, contract_id, description, unit_price, unit)                      → contracts

Master data (loaded from `_shared/`): vendors (legal_name, tax_id_last4, w9_on_file, is_1099, 1099_box, default_terms,
  default_gl, remit_bank_last4, bank_changed_at, status) · accounts (gl_number, name, type, is_prepaid) ·
  periods (period, status, closed_by, closed_at) · approval_limits (role, max_amount) · budgets (period, gl_number, department, amount)
Controls: approvals (doc_type, vendor, number, approver, role, approved_at, limit_applied) · gl_sync (erp_id, posted_at, status) ·
  bank_transactions (from `02_extracted/BANK-*.csv`) · payment_status (issued | cleared | void | stale | no bank data) ·
  accruals · prepaid_schedule · cash_requirements

invoice_balances (view): vendor, invoice_no, total, paid, open_balance, status (open | partial | paid | overpaid)
ap_aging (view): unpaid invoices with days_past_due, bucket, currency, open_home (home currency)
po_status (view): vendor, po_no, ordered, billed, remaining, status (open | partly billed | fully billed | over-billed)
unapplied_payments · vendor_credits · contract_price_variance · budget_vs_actual · discounts · not_posted ·
outstanding_payments · vendor_1099 (views)
records: every loaded document (type, vendor, number, vendor_raw, date, amount, human_approved, source_file)
review_queue · refused_duplicates · exceptions(kind, detail) · deadlines(status, days_left) · settings(as_of, functional_currency)

Links: invoice.po_no → purchase_orders · receipt.po_no → purchase_orders (3-way match) · payment_applications.invoice_no → invoices ·
       invoice → contract when the vendor matches and the invoice date is inside the contract term
Broken or suspicious links are listed in `03_data/exceptions.md` (they never block loading).

## Done means
A dropped document becomes a reviewed record, appears in the database, and can be answered about. Nothing more.
