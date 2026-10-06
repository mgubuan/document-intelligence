# Document Intelligence

Turn a client's invoices, purchase orders, payments, and contracts into clean, linked records, then ask questions about them in plain English.

Local and folder-based. No app, no server, no database to install. One AI agent ([Claude Code](https://claude.com/claude-code)) does the reading; small Python scripts do everything else.

> **Open `guide.html` in a browser** for an interactive walkthrough: follow one invoice through the system, try the vendor cleanup, break things and watch the checks catch them.

## What it does

- **Reads documents once.** Claude extracts each PDF into a plain markdown record — the source of truth.
- **Standardizes the mess.** "AMZN Mktp US", "Amazon.com", and "Amazon Marketplace" all become *Amazon*. Line items get GL codes from your chart of accounts. Anything uncertain is flagged for a person, never guessed.
- **Links documents together.** Invoices to POs, payments to invoices, invoices to contracts.
- **Catches problems.** Over-billed POs, rates above the contract, overpayments, duplicates, invoices outside a contract term, missed renewal notice windows, and documents addressed to the wrong client.
- **Closes the month.** Goods receipts for a 3-way match, posting periods with closed-period and cutoff checks, accruals (received-not-invoiced and missing contract charges), prepaid schedules, approvals with limits and segregation-of-duties checks, a vendor master (1099s, W-9s, bank-change and shared-bank-account alerts), bank matching (cleared, outstanding, unrecorded), vendor credits, a cash forecast, budget vs actual, tax and FX, early-pay discounts, and what's posted to the GL.
- **Answers questions.** A SQLite database for the numbers (spend, aging, what's open) and a knowledge graph for relationships ("how does Riverside relate to Acme?").
- **Tested.** `python _system/selftest.py` asks 137 common accountant questions of a built-in test client and checks every answer.

## Install (about 5 minutes)

1. **Python 3.** Check with `python --version`. Nothing else to install: the scripts use only the standard library.
2. **Download this repo.** Green **Code** button → **Download ZIP**, then unzip somewhere local (e.g. Documents). Or `git clone https://github.com/mgubuan/document-intelligence`.
3. **Open the folder in Claude Code** (desktop app or `claude` in a terminal) and say **"get started."**

That's it. Claude runs `python _system/start.py` first, every session. It shows whose books these are, what state they're in, and the one next step, then walks you through it:

```
CLIENT: Riverside Dental
Setup   client OK · vendor list OK · chart of accounts OK · inbox OK
State   3 new documents · 0 flagged · database up to date
NEXT STEP
  Extract 3 new document(s). Follow 02_extracted/CONTEXT.md ...
```

## Daily use

| Say to Claude | What happens |
|---|---|
| "Get started" / "Process the inbox" | Extracts new documents, cleans them, lists anything flagged |
| "What's overdue?" | AP aging as of today |
| "What should we accrue for September?" | Received-not-invoiced plus missing contract charges |
| "Which checks are outstanding?" | Payments not yet cleared on the bank statement |
| "Any control issues?" | Over-limit approvals, segregation of duties, bank changes, missing W-9s |
| "What do we still owe Acme?" | Open balances from payments applied to invoices |
| "What renews in the next 90 days?" | Contract notice deadlines, with the clause cited |
| "What doesn't line up?" | The exceptions report |
| "How does X relate to Y?" | The knowledge graph, typo-tolerant |

## How it's organized

Built on [Interpretable Context Methodology](https://arxiv.org/abs/2603.16021) (ICM): the folders are the system, and each folder's `CONTEXT.md` tells the agent what to do there.

```
CLAUDE.md          start here: routing for the agent (step 1 = start.py)
CONTEXT.md         the pipeline and the database schema
01_inbox/          documents come in (or point inbox_path at a synced SharePoint folder)
02_extracted/      one markdown record per document — the source of truth
03_data/           invoices.db + exceptions.md — generated, rebuilt anytime
04_graph/          triples.csv — generated knowledge graph
_shared/           YOUR lists: client name, vendors + aliases, chart of accounts
_templates/        record formats: invoice, purchase order, payment, contract
_system/           start, standardize, rebuild, graph, query, selftest scripts
```

**One workspace = one client.** Make a copy of this folder per client. Each workspace names its client, and documents addressed to anyone else are held for review.

## Privacy

Files stay on your computer. When the agent reads a document, its content is sent to Anthropic for processing. Under a commercial Claude plan (Team, Enterprise, or API) it is not used for training. For HIPAA or other regulated data, use Claude Enterprise or the API with a signed BAA and zero data retention, and keep sessions local. Personal Free/Pro/Max plans are not suitable for client data. The scripts themselves make no network calls. Not legal advice — have counsel review regulated setups.

## For developers

- `python _system/selftest.py` must stay at 137/137 (every question) after any change. Add failing real-world questions to its question bank.
- `INTEL_AS_OF=YYYY-MM-DD` pins "today" for aging and deadlines.
- `python _system/standardize.py --all` re-codes settled history (use only before a period is closed). Records with `approved_by_human: true` are never changed.

## License

MIT. Built by [Intelligence Solved](https://intelligencesolved.com).
