# 02_extracted — turn a document into a clean record

One job: one document in, one standardized markdown record out.

## Inputs
- Working (this run): the files listed by `python ../_system/inbox.py` (the inbox may be a SharePoint folder outside this workspace)
- Reference (every run): `../_templates/` — pick the template for the document type and copy its format exactly
- Reference (every run): `../_shared/` — read by the script, not by you

Do NOT load: other records, `03_data/`, `04_graph/`.

## Process
1. Decide what the document is, then copy the matching template:
   - invoice, bill, credit memo, receipt → `invoice.md` → save as `<invoice_no>.md` (fill `po_no` if a PO number is printed)
   - purchase order → `purchase_order.md` → save as `PO-<po_no>.md`
   - check stub, remittance advice, ACH/wire confirmation, card charge → `payment.md` → save as `PMT-<payment_id>.md`, one row per invoice the payment covers
   - contract, agreement, lease, subscription terms, signed quote → `contract.md` → save as `CTR-<contract_id>.md`
     Use the strongest model available for contracts. Read the whole document, including amendments and schedules.
     Quote the contract's own wording in Key terms and cite the section. Never infer a renewal or notice term that isn't written down — use `unknown` / blank.
     Write rate descriptions with the same wording the vendor's invoices use, so rates can be checked.
   Fill it in from the document. Set `source_file` to the exact value `inbox.py` printed for it.
   Fill `client` with the name exactly as printed on the document. If it isn't this workspace's client, still record it: the script will hold it for review.
   Anything else (W-9, fixed-asset form, statement)? Skip it and tell the user. Those types aren't built yet.
2. Write the vendor name EXACTLY as printed in `vendor_raw`. Never clean it up — that's the script's job.
3. Unreadable field → `UNKNOWN`. Never guess a number.
4. Run `python ../_system/standardize.py`. It adds the clean vendor, doc type, GL codes, a confidence score, and flags anything uncertain — including line items that don't add up to the total.
5. Run `python ../_system/rebuild.py`.

## Outputs
- `<invoice_no>.md` → this folder

## Human check
Every contract is held for review until a person checks its key terms, dates, renewal and notice clauses against the signed copy, then adds `approved_by_human: true`.

Open every record with `needs_review: true`. Either fix the master list in `../_shared/` (preferred — it fixes every future invoice too) and re-run step 4, or correct the record and add the line `approved_by_human: true` to its frontmatter, then re-run step 4. (Setting `needs_review: false` by hand gets overwritten.)
