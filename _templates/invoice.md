---
record_type: invoice
invoice_no: INV-0000
vendor_raw: Vendor name exactly as printed
client: Client Name
date: 2026-01-31
due_date: 2026-02-28
total: 0.00
currency: USD
fx_rate:
tax_amount:
tax_type:
freight:
discount_pct:
discount_days:
po_no:
applies_to:
service_start:
service_end:
posting_period:
department:
class:
location:
project:
entity:
source_file: path/relative/to/inbox.pdf
extracted_by: agent
extracted_on: 2026-01-31
approved_by:
approver_role:
approved_at:
erp_id:
posted_at:
gl_status:
---
# Invoice INV-0000

From [[Vendor name exactly as printed]] to [[Client Name]].

| description | qty | unit_price | amount |
|---|---|---|---|
| Example service | 1 | 0.00 | 0.00 |

<!--
How to fill the optional fields (leave blank if the document doesn't say):
- total: the full amount due. Line items + tax_amount + freight must add up to it.
- currency / fx_rate: if not the home currency in _shared/settings.md, fx_rate converts 1 unit to home currency.
- discount_pct / discount_days: early-pay terms, e.g. "2/10 net 30" -> 2 and 10.
- service_start / service_end: the period the goods or services cover, if printed.
- posting_period: YYYY-MM the person wants it booked to; blank = the invoice date's month.
- applies_to: on a credit memo, the invoice number it credits (only if printed).
- department / class / location / project / entity: reporting dimensions, if the client uses them.
- extracted_by / extracted_on: who created this record and the date. Always fill these.
- approved_by / approver_role / approved_at: only from a real approval (stamp, email, workflow). Never invent one.
- erp_id / posted_at / gl_status: filled after the bill is posted to QuickBooks or another system (gl_status: posted).
-->
