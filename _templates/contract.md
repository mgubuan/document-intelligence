---
record_type: contract
contract_id: contract number, or VENDOR-YYYY-short-name if none is printed
vendor_raw: Counterparty exactly as printed
client: Client Name
title: e.g. Bookkeeping services agreement
contract_type: service | lease | subscription | purchase | NDA | other
effective_date: 2026-01-01
end_date: 2026-12-31 (blank if it has no end date)
auto_renew: yes | no | unknown
renewal_term: e.g. 12 months (blank if no auto-renew)
notice_days: days of notice required to cancel or not renew (blank if none stated)
payment_terms: e.g. Net 30
billing_frequency: monthly | quarterly | annual | one-time | other
recurring_amount: amount per billing period (blank if not fixed)
total_value: total contract value (blank if not stated)
currency: USD
source_file: path/relative/to/inbox.pdf
---
# Contract

Between [[Client Name]] and [[Counterparty exactly as printed]].

## Key terms
Quote the contract's own words where possible and cite the section.

| term | value | section |
|---|---|---|
| termination | e.g. Either party, 60 days written notice | §8.2 |
| price increases | e.g. Up to 5% per renewal with 30 days notice | §4.3 |
| liability cap | e.g. Fees paid in the prior 12 months | §10.1 |

## Rates
Agreed prices. Use the same description wording the invoices use.

| description | unit_price | unit |
|---|---|---|
| Example service | 0.00 | month |
