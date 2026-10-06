---
record_type: purchase_order
po_no: PO-0000
vendor_raw: Vendor name exactly as printed
client: Client Name (who issued the PO)
date: 2026-01-31
total: 0.00
currency: USD
receipt_required: yes
source_file: path/relative/to/inbox.pdf
---
# Purchase order PO-0000

Ordered by [[Client Name]] from [[Vendor name exactly as printed]].

| description | qty | unit_price | amount |
|---|---|---|---|
| Example item | 1 | 0.00 | 0.00 |

<!--
- receipt_required: yes for goods (a receipt must be logged before the invoice clears the 3-way match);
  no for services or subscriptions where nothing is physically received.
-->
