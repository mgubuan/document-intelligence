# Document Intelligence Layer

Turns invoices, purchase orders, payments, and contracts into clean, linked records you can ask questions about. Local, folder-based, one agent.

The folders are the system. Each folder's CONTEXT.md is its contract — read it before working there, and don't load folders the task doesn't need.

## Step 1, every session: run `python _system/start.py`

Before anything else, whatever the user asked. It prints whose books these are, what state they're in, and the ONE next step. Do that step, then run `start.py` again. Repeat until it says **Ready**.

- Tell the user the client name it shows. If it's not the client they meant, stop. They opened the wrong folder.
- "Process the inbox", "get started", "what's next", "catch me up" all mean: run `start.py` and follow it.
- One workspace = one client. Never point `inbox_path` at a folder that holds several clients' documents.

## Where things live

| Folder | What it holds |
|---|---|
| `01_inbox/` | raw invoices — or wherever `_shared/settings.md` points (e.g. SharePoint) |
| `02_extracted/` | one markdown record per document (invoice, PO, receipt, payment, contract) + bank CSVs — the source of truth |
| `03_data/` | invoices.db + exceptions.md — generated, never hand-edited |
| `04_graph/` | triples.csv — generated, never hand-edited |
| `_shared/` | factory: vendor list, chart of accounts, doc types (user-owned) |
| `_templates/` | one record format per document type — every record starts as a copy |
| `_system/` | the scripts: `start.py` (step 1), and `selftest.py` (question check) |

## Route by what just happened

| If | Go to | Then stop at |
|---|---|---|
| session starts, or "process the inbox" / "what's next" | `python _system/start.py` | do the NEXT STEP it prints, then run it again |
| new files in the inbox (start.py lists them) | `02_extracted/CONTEXT.md` | list flagged documents for the user |
| user fixed `_shared/` or a flagged record | run `python _system/standardize.py && python _system/rebuild.py` | report what's still flagged |
| user asks a question about amounts | `03_data/CONTEXT.md` | answer with document numbers cited |
| user asks how things relate ("how does X relate to Y", "who do we use for…") | run `python _system/graph.py "X" "Y"`, then add amounts from `03_data` | plain-English answer, documents cited |
| asked for status | run `python _system/start.py` | report its state lines and any matching exceptions |
| asked what's paid or open | `03_data/CONTEXT.md` (invoice_balances) | answer with invoice numbers cited |
| asked about month-end: accruals, cutoff, closed periods, prepaids | `03_data/CONTEXT.md` (accruals, periods, prepaid_schedule) | answer with documents cited; list accruals as suggestions, not entries |
| asked about bank rec, outstanding checks, cash needs, discounts | `03_data/CONTEXT.md` (payment_status, cash_requirements, discounts) | answer with payment / invoice numbers cited |
| asked about approvals, 1099s, vendor bank changes, controls | `03_data/CONTEXT.md` (approvals, vendor_1099, exceptions) | answer with names and documents cited |
| asked about renewals, notice dates, or contract terms | `03_data/CONTEXT.md` (contracts) | answer with the contract section cited |

## The one rule

Nothing flagged `needs_review: true` reaches the database. A person clears it first.
Never edit `_shared/` yourself — tell the user what to add and let them decide. The one exception: setting the client name with `start.py --client`, using exactly the name the user confirms.
