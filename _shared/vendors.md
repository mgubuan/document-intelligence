# Vendor master list
One row per real vendor. Add every spelling you've seen to aliases (separate with ;).
When an invoice gets flagged, fix it here and it never gets flagged again.

Only `vendor` and `aliases` are required. The rest power 1099 reporting and fraud checks:
- `tax_id_last4`: last 4 digits only. Never store full tax IDs here.
- `is_1099` / `1099_box`: yes|no, and the box (e.g. NEC-1, MISC-1 rent).
- `w9_on_file`: yes|no. A 1099 vendor paid $600+ in a year with no W-9 is flagged.
- `remit_bank_last4` / `bank_changed_at`: when the vendor's bank details change, payments in the
  next 30 days are flagged. Changed remit-to banks are the most common AP fraud.
- `status`: active|inactive. Invoices from inactive vendors are flagged.

| vendor | aliases | legal_name | tax_id_last4 | w9_on_file | is_1099 | 1099_box | default_terms | default_gl | remit_bank_last4 | bank_changed_at | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Acme Bookkeeping | ACME Bookkeeping LLC; Acme Bkpg; Acme Bookkeeping Services | Acme Bookkeeping Services, LLC | 4821 | yes | yes | NEC-1 | Net 15 | 6100 | 1177 | | active |
| Amazon | AMZN Mktp US; Amazon.com; Amazon Marketplace | Amazon.com Services LLC | | no | no | | Due on receipt | 6400 | | | active |
| Amazon Web Services | AWS; Amazon Web Services Inc | Amazon Web Services, Inc. | | no | no | | Net 30 | 6300 | | | active |
| Intuit | QuickBooks; Intuit Inc; QBO | Intuit Inc. | | no | no | | Card | 6300 | | | active |
