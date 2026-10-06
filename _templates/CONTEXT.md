# _templates — one record format per document type

| Template | For | Save record as |
|---|---|---|
| `invoice.md` | invoices, bills, credit memos, purchase receipts (proof of a purchase) | `<invoice_no>.md` |
| `purchase_order.md` | purchase orders | `PO-<po_no>.md` |
| `payment.md` | checks, ACH/wire remittances, card charges | `PMT-<payment_id>.md` |
| `receipt.md` | goods receipts: packing slips, delivery notes, receiving logs | `RCV-<receipt_id>.md` |
| `contract.md` | contracts, agreements, leases, subscriptions | `CTR-<contract_id>.md` |

Every record starts as a copy. The scripts depend on the exact keys and table columns — change a template and the schema in the root `CONTEXT.md` together.

Bank statements aren't markdown: save them as `02_extracted/BANK-<account>-<YYYY-MM>.csv` with columns
`txn_id,account,date,amount,description,reference,source_file` (money out is negative;
`source_file` is the bank export it came from, so the inbox knows it's done).
