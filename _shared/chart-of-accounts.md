# Chart of accounts
Line items get coded to one of these. Keywords drive the matcher.
`type`: asset | liability | equity | income | expense. `is_prepaid: yes` marks prepaid asset accounts:
invoices coded there are spread over their service period (see prepaid_schedule).

| account | keywords | type | is_prepaid |
|---|---|---|---|
| 1400 Prepaid Expenses | annual premium; prepaid; insurance | asset | yes |
| 6100 Accounting & Bookkeeping | bookkeeping; accounting; tax prep; cleanup; reconciliation | expense | no |
| 6150 Payroll Services | payroll; w-2; 1099 filing | expense | no |
| 6300 Software & Subscriptions | software; subscription; saas; license; quickbooks; hosting | expense | no |
| 6400 Office Supplies | paper; toner; supplies; pens | expense | no |
| 6500 Professional Services | consulting; legal; advisory | expense | no |
| 9999 Uncategorized | | expense | no |
