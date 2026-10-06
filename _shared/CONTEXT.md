# _shared — the factory: your approved lists and settings

Owned by the user (the bookkeeper or controller). The agent reads these through the scripts and never edits them
(the one exception: `start.py --client` sets the client name the user confirms).

| File | What it holds | Powers |
|---|---|---|
| `settings.md` | client name, inbox path, home currency, accrual lookback | everything |
| `vendors.md` | real vendor names, aliases, W-9 / 1099 status, remit bank changes, active/inactive | vendor cleanup, 1099 report, fraud checks |
| `chart-of-accounts.md` | GL accounts, matching keywords, account type, prepaid flag | GL coding, prepaid schedule |
| `doc-types.md` | invoice, credit memo, statement, receipt keywords | document type |
| `periods.md` | which months are open or closed, by whom, when | late-entry and cutoff checks |
| `approval-limits.md` | how much each role may approve | approval-limit and segregation-of-duties checks |
| `budgets.md` | monthly budget by GL account and department | budget vs actual |

When something gets flagged, the fix usually belongs here: add the alias or keyword once and it never flags again.
