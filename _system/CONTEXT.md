# _system — the scripts (no AI inside)

| Script | Does | Run from anywhere |
|---|---|---|
| `start.py` | **step 1 of every session**: client, setup check, state, and the one next step | `python _system/start.py` |
| `standardize.py` | cleans names against `_shared/`, codes line items, checks that lines (or payment splits) add up, sets `needs_review`. Only touches new and flagged records | `python _system/standardize.py` |
| `rebuild.py` | rebuilds `03_data/` (database + exceptions) and `04_graph/` from approved records, prints status | `python _system/rebuild.py` |
| `inbox.py` | lists invoices that don't have a record yet (searches subfolders) | `python _system/inbox.py` |
| `graph.py` | how things relate: links and paths between two names (typo-tolerant) | `python _system/graph.py "riverside" "acme"` |
| `selftest.py` | asks 100 accountant questions of a built-in test client and checks every answer | `python _system/selftest.py` |
| `q.py` | runs one SQL query | `python _system/q.py "SELECT ..."` |

All scripts are offline: no AI, no network calls. The only AI step is the agent reading documents (and suggesting fixes for flagged items, which a person approves).

## Protecting history
`standardize.py` never re-codes records that are already settled, so editing `_shared/` can't silently change closed periods.
`--all` re-codes everything except `approved_by_human` records. Only run it when the user explicitly asks, and say which records changed.

## After changing any script
Run `python _system/selftest.py`. It must stay at 100/100. If a real user question fails, add it to the question bank in `selftest.py` (with the test client in `tests/fixture/` if it needs new data), then fix the system until it passes.
