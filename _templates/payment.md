---
record_type: payment
payment_id: check number, ACH/wire reference, or card transaction ID
vendor_raw: Payee exactly as printed
client: Client Name (who paid)
date: 2026-01-31
amount: 0.00
method: check | ACH | wire | card
currency: USD
source_file: path/relative/to/inbox.pdf
---
# Payment

[[Client Name]] paid [[Payee exactly as printed]].

Which invoices this payment covers (from the remittance or memo). One row per invoice.

| invoice_no | amount_applied |
|---|---|
| INV-0000 | 0.00 |
