# _templates — one record format per document type

| Template | For | Save record as |
|---|---|---|
| `invoice.md` | invoices, bills, credit memos, receipts | `<invoice_no>.md` |
| `purchase_order.md` | purchase orders | `PO-<po_no>.md` |
| `payment.md` | checks, ACH/wire remittances, card charges | `PMT-<payment_id>.md` |
| `contract.md` | contracts, agreements, leases, subscriptions | `CTR-<contract_id>.md` |

Every record starts as a copy. The scripts depend on the exact keys and table columns — change a template and the schema in the root `CONTEXT.md` together.
