"""Self-test: 100 questions an accountant would ask, run against a known test client.

    python _system/selftest.py            -> runs all 100, prints failures and a score
    python _system/selftest.py -v         -> also prints every answer

It copies the scripts and the test client in _system/tests/fixture/ into a temporary folder,
runs standardize + rebuild there as of 2026-10-05, then asks each question the way the agent
would (SQL, graph, or status script) and checks the answer. Your real data is never touched.

Each question names the route the agent should take. If a question here fails, the agent will
fail it too: fix the system (scripts, views, CONTEXT.md), not the test.
"""
import os, pathlib, shutil, sqlite3, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
VERBOSE = "-v" in sys.argv
AS_OF = "2026-10-05"

# ---------------------------------------------------------------- the question bank
# (area, question, route, query-or-args, [expected fragments])
SQL, GRAPH, STATUS, INBOX, FILE, START, START_NEW = "sql", "graph", "status", "inbox", "file", "start", "start_new"
X = "SELECT detail FROM exceptions WHERE kind="  # shorthand for exception questions
Q = [
# A. Spend --------------------------------------------------------------------------------------
("Spend", "How much did we spend in September?", SQL,
 "SELECT ROUND(SUM(total),2) FROM invoices WHERE date LIKE '2026-09%'", ["7711.4"]),
("Spend", "What did we spend with each vendor?", SQL,
 "SELECT vendor, ROUND(SUM(functional_amount),2) FROM invoices GROUP BY vendor ORDER BY 2 DESC",
 ["Oak Street Properties | 8000.0", "Acme Bookkeeping | 3800.0", "Harbor Insurance | 2400.0", "Pacific Dental Supply | 2350.0", "Nordic Dental | 583.2", "Amazon | 204.3"]),
("Spend", "What did we spend by GL account in September?", SQL,
 "SELECT l.gl_account, ROUND(SUM(l.amount),2) FROM line_items l JOIN invoices i USING (vendor, invoice_no) WHERE i.date LIKE '2026-09%' GROUP BY 1",
 ["5100 Dental Supplies | 2050.0", "6200 Rent | 4000.0", "6300 Software & Subscriptions | 127.1", "6400 Office Supplies | 84.3"]),
("Spend", "How much have we spent on office supplies?", SQL,
 "SELECT ROUND(SUM(amount),2) FROM line_items WHERE gl_account LIKE '6400%'", ["204.3"]),
("Spend", "How much do we spend on software?", SQL,
 "SELECT ROUND(SUM(amount),2) FROM line_items WHERE gl_account LIKE '6300%'", ["127.1"]),
("Spend", "How many invoices did we get in September?", SQL,
 "SELECT COUNT(*) FROM invoices WHERE date LIKE '2026-09%'", ["8"]),
("Spend", "What's our average invoice?", SQL,
 "SELECT ROUND(AVG(functional_amount),2) FROM invoices", ["1164.31"]),
("Spend", "What was the largest invoice?", SQL,
 "SELECT vendor, invoice_no, total FROM invoices ORDER BY total DESC LIMIT 2", ["Oak Street Properties", "4000.0"]),
("Spend", "Show spend by month.", SQL,
 "SELECT substr(date,1,7), ROUND(SUM(functional_amount),2) FROM invoices GROUP BY 1 ORDER BY 1",
 ["2025-12 | 950.0", "2026-08 | 1400.0", "2026-09 | 7711.4", "2026-10 | 7403.2"]),
("Spend", "How much rent have we paid this year?", SQL,
 "SELECT ROUND(SUM(l.amount),2) FROM line_items l JOIN invoices i USING (vendor, invoice_no) WHERE l.gl_account LIKE '6200%' AND i.date LIKE '2026%'", ["8000.0"]),
("Spend", "What did Acme bill us for?", SQL,
 "SELECT invoice_no, description, amount FROM line_items WHERE vendor = 'Acme Bookkeeping' ORDER BY invoice_no",
 ["Monthly bookkeeping", "Payroll processing"]),
("Spend", "Is anything coded to Uncategorized?", SQL,
 "SELECT COUNT(*) FROM line_items WHERE gl_account LIKE '9999%'", ["0"]),
("Spend", "Which vendors did we buy from in Q3?", SQL,
 "SELECT DISTINCT vendor FROM invoices WHERE date BETWEEN '2026-07-01' AND '2026-09-30' ORDER BY 1",
 ["Acme Bookkeeping", "Amazon", "Amazon Web Services", "Intuit", "Oak Street Properties", "Pacific Dental Supply"]),

# B. Open balances and aging --------------------------------------------------------------------
("Payables", "What's unpaid right now?", SQL,
 "SELECT vendor, invoice_no, open_balance FROM ap_aging ORDER BY vendor",
 ["INV-1001 | 500.0", "PDS-3301 | 100.0", "PDS-3388 | 950.0", "AWS-0925 | 42.1"]),
("Payables", "What's our total open AP?", SQL,
 "SELECT ROUND(SUM(open_home),2) FROM ap_aging", ["4875.3"]),
("Payables", "What do we owe each vendor?", SQL,
 "SELECT vendor, ROUND(SUM(open_home),2) FROM ap_aging GROUP BY vendor ORDER BY 1",
 ["Acme Bookkeeping | 500.0", "Pacific Dental Supply | 1350.0", "Amazon Web Services | 42.1", "Harbor Insurance | 2400.0", "Nordic Dental | 583.2"]),
("Payables", "Which invoices are partly paid?", SQL,
 "SELECT invoice_no, paid, open_balance FROM invoice_balances WHERE status = 'partial'", ["INV-1001", "PDS-3301"]),
("Payables", "What's overdue?", SQL,
 "SELECT invoice_no, due_date, days_past_due, open_balance FROM ap_aging WHERE days_past_due > 0 ORDER BY days_past_due DESC",
 ["AWS-0925 | 2026-09-25 | 10", "INV-1001 | 2026-09-30 | 5"]),
("Payables", "Give me an AP aging summary.", SQL,
 "SELECT bucket, ROUND(SUM(open_home),2) FROM ap_aging GROUP BY bucket", ["current | 4333.2", "1-30 | 542.1"]),
("Payables", "What's the oldest unpaid invoice?", SQL,
 "SELECT invoice_no, due_date FROM ap_aging ORDER BY due_date LIMIT 1", ["AWS-0925"]),
("Payables", "What comes due in the next 30 days?", SQL,
 "SELECT invoice_no, due_date, open_balance FROM ap_aging WHERE due_date BETWEEN (SELECT as_of FROM settings) AND date((SELECT as_of FROM settings), '+30 days')",
 ["PDS-3301 | 2026-10-10", "PDS-3388 | 2026-10-28"]),
("Payables", "Did we overpay anything?", SQL,
 "SELECT invoice_no, total, paid FROM invoice_balances WHERE status = 'overpaid'", ["RENT-1001 | 4000.0 | 4100.0"]),
("Payables", "Which invoices are fully paid?", SQL,
 "SELECT invoice_no FROM invoice_balances WHERE status = 'paid' ORDER BY 1",
 ["AMZ-55821", "AMZ-56010", "INV-0815", "INV-0901", "QB-77", "RENT-0901"]),
("Payables", "What do we still owe Acme?", SQL,
 "SELECT invoice_no, open_balance FROM ap_aging WHERE vendor = 'Acme Bookkeeping'", ["INV-1001 | 500.0"]),
("Payables", "When is RENT-1001 due?", SQL,
 "SELECT due_date FROM invoices WHERE invoice_no = 'RENT-1001'", ["2026-10-01"]),
("Payables", "Do we have any credits with vendors?", SQL,
 "SELECT vendor, invoice_no, open_balance FROM invoice_balances WHERE open_balance < 0",
 ["PDS-CM-3301 | -100.0", "RENT-1001 | -100.0"]),

# C. Payments -----------------------------------------------------------------------------------
("Payments", "How much did we pay out in September?", SQL,
 "SELECT ROUND(SUM(amount),2) FROM payments WHERE date LIKE '2026-09%'", ["6519.3"]),
("Payments", "How did we pay, by method?", SQL,
 "SELECT method, COUNT(*), ROUND(SUM(amount),2) FROM payments GROUP BY method ORDER BY 1",
 ["ACH | 2 | 2350.0", "card | 3 | 289.3", "check | 4 | 10150.0"]),
("Payments", "Which invoices did check 2001 pay?", SQL,
 "SELECT invoice_no, amount FROM payment_applications WHERE payment_id = 'CHK-2001'", ["RENT-0901 | 4000.0"]),
("Payments", "How much have we paid Oak Street?", SQL,
 "SELECT ROUND(SUM(amount),2) FROM payments WHERE vendor = 'Oak Street Properties'", ["8100.0"]),
("Payments", "Is any payment not fully applied to invoices?", SQL,
 "SELECT p.payment_id FROM payments p LEFT JOIN payment_applications a USING (vendor, payment_id) GROUP BY p.vendor, p.payment_id HAVING ABS(p.amount - COALESCE(SUM(a.amount),0)) > 0.01",
 ["(no rows)"]),
("Payments", "What was our largest payment?", SQL,
 "SELECT payment_id, vendor, amount FROM payments ORDER BY amount DESC LIMIT 1", ["CHK-2003", "4100.0"]),
("Payments", "How do we pay Amazon?", SQL,
 "SELECT DISTINCT method FROM payments WHERE vendor = 'Amazon'", ["card"]),
("Payments", "What did we pay in October?", SQL,
 "SELECT payment_id, amount FROM payments WHERE date LIKE '2026-10%' ORDER BY 1",
 ["CARD-1002 | 120.0", "CHK-2002 | 1100.0", "CHK-2003 | 4100.0"]),
("Payments", "When did we pay INV-0901, and how?", SQL,
 "SELECT p.date, p.payment_id, p.method FROM payments p JOIN payment_applications a USING (vendor, payment_id) WHERE a.invoice_no = 'INV-0901'",
 ["2026-09-05 | ACH-0905 | ACH"]),

# D. Purchase orders ----------------------------------------------------------------------------
("POs", "Which POs are still open?", SQL,
 "SELECT po_no, remaining FROM po_status WHERE status IN ('open', 'partly billed')", ["PO-7105 | 800.0"]),
("POs", "How much has been billed against PO-7001?", SQL,
 "SELECT ordered, billed, remaining, status FROM po_status WHERE po_no = 'PO-7001'", ["2000.0 | 2150.0 | -150.0 | over-billed"]),
("POs", "Are any POs over-billed?", SQL,
 "SELECT vendor, po_no FROM po_status WHERE status = 'over-billed'", ["Pacific Dental Supply | PO-7001"]),
("POs", "Which invoices have no PO?", SQL,
 "SELECT COUNT(*) FROM invoices WHERE po_no IS NULL", ["11"]),
("POs", "How much is left on PO-5001?", SQL,
 "SELECT remaining, status FROM po_status WHERE po_no = 'PO-5001'", ["0.0 | fully billed"]),
("POs", "What have we ordered from each vendor?", SQL,
 "SELECT vendor, ROUND(SUM(total),2) FROM purchase_orders GROUP BY vendor ORDER BY 1",
 ["Acme Bookkeeping | 1450.0", "Pacific Dental Supply | 2800.0"]),
("POs", "Which PO did INV-1001 bill against?", SQL,
 "SELECT po_no FROM invoices WHERE invoice_no = 'INV-1001'", ["PO-5001"]),
("POs", "What's on PO-7105?", SQL,
 "SELECT description, qty, amount FROM po_lines WHERE po_no = 'PO-7105'", ["Sterilization pouches | 8.0 | 800.0"]),
("POs", "What POs did we issue in October?", SQL,
 "SELECT po_no FROM purchase_orders WHERE date LIKE '2026-10%'", ["PO-7105"]),
("POs", "Does any invoice cite a PO we don't have?", SQL,
 "SELECT detail FROM exceptions WHERE detail LIKE '%references PO%'", ["AWS-0925", "PO-9999"]),

# E. Contracts ----------------------------------------------------------------------------------
("Contracts", "What contracts need a decision in the next 90 days?", SQL,
 "SELECT vendor, notice_deadline, days_left FROM deadlines WHERE status = 'upcoming' ORDER BY notice_deadline",
 ["Acme Bookkeeping | 2026-11-01 | 27", "Pacific Dental Supply | 2026-12-01 | 57"]),
("Contracts", "When do we have to give notice on Acme?", SQL,
 "SELECT notice_deadline, auto_renew, renewal_term FROM contracts WHERE vendor = 'Acme Bookkeeping'", ["2026-11-01 | yes | 12 months"]),
("Contracts", "Did we miss any notice deadlines?", SQL,
 "SELECT vendor, contract_id, notice_deadline FROM deadlines WHERE status = 'missed'", ["Oak Street Properties | OAK-LEASE-2024 | 2026-10-02"]),
("Contracts", "How do we terminate the Acme contract?", SQL,
 "SELECT value, section FROM contract_terms WHERE vendor = 'Acme Bookkeeping' AND term = 'termination'", ["60 days written notice", "§8.2"]),
("Contracts", "Is anyone billing above their contract rate?", SQL,
 "SELECT detail FROM exceptions WHERE kind = 'Above contract rate'", ["INV-1001", "225.00", "PDS-3301", "55.00"]),
("Contracts", "Any invoices outside a contract term?", SQL,
 "SELECT detail FROM exceptions WHERE kind = 'Outside contract'", ["INV-0815"]),
("Contracts", "When does the office lease end?", SQL,
 "SELECT end_date FROM contracts WHERE contract_type = 'lease'", ["2026-12-31"]),
("Contracts", "Which contracts auto-renew?", SQL,
 "SELECT contract_id FROM contracts WHERE auto_renew = 'yes' ORDER BY 1", ["ACME-2026-BOOKKEEPING", "INTUIT-QBO"]),
("Contracts", "What contracts do we have?", SQL,
 "SELECT COUNT(*) FROM contracts", ["4"]),
("Contracts", "Are we over any contract's value?", SQL,
 "SELECT detail FROM exceptions WHERE kind = 'Over contract value'", ["PDS-SUPPLY-2026", "2350.00"]),
("Contracts", "What's the liability cap with Acme?", SQL,
 "SELECT value, section FROM contract_terms WHERE vendor = 'Acme Bookkeeping' AND term = 'liability cap'", ["12 months", "§10.1"]),
("Contracts", "Can Acme raise prices?", SQL,
 "SELECT value, section FROM contract_terms WHERE vendor = 'Acme Bookkeeping' AND term LIKE '%price%'", ["5%", "§4.3"]),
("Contracts", "How much is the security deposit on the lease?", SQL,
 "SELECT value, section FROM contract_terms WHERE contract_id = 'OAK-LEASE-2024' AND term LIKE '%deposit%'", ["$8,000", "§5.1"]),
("Contracts", "What's the agreed price for gloves?", SQL,
 "SELECT unit_price, unit FROM contract_rates WHERE description LIKE '%gloves%'", ["55.0 | case"]),
("Contracts", "What does QuickBooks cost us per month?", SQL,
 "SELECT recurring_amount, billing_frequency FROM contracts WHERE vendor = 'Intuit'", ["85.0 | monthly"]),

# F. Vendors ------------------------------------------------------------------------------------
("Vendors", "Which vendors do we use?", SQL,
 "SELECT DISTINCT vendor FROM records ORDER BY 1",
 ["Acme Bookkeeping", "Amazon", "Amazon Web Services", "Intuit", "Oak Street Properties", "Pacific Dental Supply"]),
("Vendors", "How many vendors do we have?", SQL,
 "SELECT COUNT(DISTINCT vendor) FROM records", ["8"]),
("Vendors", "What names has Acme appeared under?", SQL,
 "SELECT DISTINCT vendor_raw FROM records WHERE vendor = 'Acme Bookkeeping' ORDER BY 1",
 ["ACME Bookkeeping LLC", "Acme Bookkeeping Services"]),
("Vendors", "Which vendors have contracts?", SQL,
 "SELECT DISTINCT vendor FROM contracts ORDER BY 1", ["Acme Bookkeeping", "Intuit", "Oak Street Properties", "Pacific Dental Supply"]),
("Vendors", "Which vendors have no contract?", SQL,
 "SELECT DISTINCT vendor FROM invoices WHERE vendor NOT IN (SELECT vendor FROM contracts) ORDER BY 1", ["Amazon", "Amazon Web Services"]),
("Vendors", "When did we first buy from Pacific Dental?", SQL,
 "SELECT MIN(date) FROM invoices WHERE vendor = 'Pacific Dental Supply'", ["2026-09-10"]),
("Vendors", "Which vendor names couldn't be matched?", SQL,
 "SELECT vendor_raw, reason FROM review_queue WHERE reason LIKE '%confidence%'", ["Bob's Plumbing"]),
("Vendors", "Who is AMZN Mktp US?", GRAPH, ["AMZN Mktp US"], ['-> Amazon']),

# G. Review and data quality --------------------------------------------------------------------
("Review", "What's waiting on review?", SQL,
 "SELECT record_type, number, reason FROM review_queue ORDER BY 2", ["BOB-118", "CHK-2004", "LAW-0042"]),
("Review", "Did another client's document get into these books?", SQL,
 "SELECT number, reason FROM review_queue WHERE reason LIKE '%this workspace is%'", ["LAW-0042", "Oak Street Law", "Riverside Dental"]),
("Getting started", "What's next? (session start)", START, None,
 ["CLIENT: Riverside Dental", "vendor list ................ 8 vendors", "chart of accounts .......... 10 accounts", "new documents in inbox ...... 1", "NEXT STEP", "Extract 1 new document", "statement-sept.pdf"]),
("Getting started", "Get started (brand-new workspace, no client named yet)", START_NEW, None,
 ["CLIENT: (not set)", "NEXT STEP", "Which client's books are these?", "--client"]),
("Review", "Why was CHK-2004 flagged?", SQL,
 "SELECT reason FROM review_queue WHERE number = 'CHK-2004'", ["sum to 800.00", "900.00"]),
("Review", "Were any duplicates refused?", SQL,
 "SELECT number, kept_file, refused_file FROM refused_duplicates", ["INV-1001 | INV-1001.md | INV-1001-copy.md"]),
("Review", "Is there anything in the inbox we haven't processed?", INBOX, None, ["Pending: 1", "statement-sept.pdf"]),
("Review", "What exceptions are open?", SQL,
 "SELECT COUNT(*) FROM exceptions", ["16"]),
("Review", "What's the status?", STATUS, None,
 ["CLIENT: Riverside Dental", "Not extracted yet: 1", "Waiting on review (not in database): 4", "Duplicates refused (already loaded): 1", "Matching exceptions: 16", "15 invoices, 3 purchase orders, 9 payments, 4 contracts, 2 receipts, 9 bank lines"]),
("Review", "How many documents are loaded?", SQL,
 "SELECT record_type, COUNT(*) FROM records GROUP BY 1 ORDER BY 1",
 ["contract | 4", "invoice | 15", "payment | 9", "purchase_order | 3", "receipt | 2"]),
("Review", "Which records did a person approve?", SQL,
 "SELECT number FROM records WHERE human_approved ORDER BY 1",
 ["ACME-2026-BOOKKEEPING", "INTUIT-QBO", "OAK-LEASE-2024", "PDS-SUPPLY-2026"]),
("Review", "What exceptions are there, by type?", SQL,
 "SELECT kind, COUNT(*) FROM exceptions GROUP BY kind ORDER BY 1",
 ["Above contract rate | 2", "Missing link | 1", "Outside contract | 1", "Over contract value | 1", "Over-billed | 1", "Overpaid | 1"]),

# H. Relationships ------------------------------------------------------------------------------
("Relationships", "How does Riverside Dental relate to Acme?", GRAPH, ["riverside detal", "acme"],
 ["-> Riverside Dental", "-> Acme Bookkeeping", "billed", "paid", "ordered_from"]),
("Relationships", "Who does Riverside pay?", GRAPH, ["riverside"],
 ["paid--> Acme Bookkeeping", "paid--> Oak Street Properties", "paid--> Pacific Dental Supply", "paid--> Amazon"]),
("Relationships", "What's connected to PO-7001?", GRAPH, ["PO-7001"],
 ["PDS-3301 --bills_against-->", "PDS-3388 --bills_against-->"]),
("Relationships", "Which vendors bill us for bookkeeping?", SQL,
 "SELECT DISTINCT vendor FROM line_items WHERE description LIKE '%bookkeeping%'", ["Acme Bookkeeping"]),
("Relationships", "Who do we buy office supplies from?", SQL,
 "SELECT DISTINCT vendor FROM line_items WHERE gl_account LIKE '6400%'", ["Amazon"]),
("Relationships", "Show everything involving Oak Street.", GRAPH, ["oak street"],
 ["RENT-0901", "RENT-1001", "CHK-2001", "OAK-LEASE-2024"]),
("Relationships", "Trace INV-1001 end to end.", GRAPH, ["INV-1001"],
 ["bills_against--> Acme Bookkeeping/PO-5001", "ACH-0930 --pays-->", "under_contract--> Acme Bookkeeping/ACME-2026-BOOKKEEPING"]),
("Relationships", "What paid AMZ-55821?", GRAPH, ["AMZ-55821"], ["Amazon/CARD-0922 --pays-->"]),
("Relationships", "How is Riverside connected to Amazon?", GRAPH, ["Riverside", "AMZN"], ["-> Amazon", "paid"]),
("Relationships", "How does Pacific Dental relate to us?", GRAPH, ["pacific dental", "riverside"],
 ["-> Pacific Dental Supply", "PO-7001", "has_contract"]),

# I. Month-end ----------------------------------------------------------------------------------
("Month-end", "What was unpaid at September 30 (accrued AP)?", SQL,
 """SELECT ROUND(SUM(i.total - COALESCE((SELECT SUM(a.amount) FROM payment_applications a JOIN payments p USING (vendor, payment_id)
      WHERE a.vendor = i.vendor AND a.invoice_no = i.invoice_no AND p.date <= '2026-09-30'), 0)), 2)
    FROM invoices i WHERE i.date <= '2026-09-30'""", ["2592.1"]),
("Month-end", "How did September compare to August?", SQL,
 "SELECT substr(date,1,7), ROUND(SUM(total),2) FROM invoices WHERE date BETWEEN '2026-08-01' AND '2026-09-30' GROUP BY 1",
 ["2026-08 | 1400.0", "2026-09 | 7711.4"]),
("Month-end", "Did we get any credit memos?", SQL,
 "SELECT vendor, invoice_no, total FROM invoices WHERE doc_type = 'credit memo'", ["PDS-CM-3301 | -100.0"]),
("Month-end", "How many receipts versus invoices?", SQL,
 "SELECT doc_type, COUNT(*) FROM invoices GROUP BY 1 ORDER BY 1", ["credit memo | 1", "invoice | 12", "receipt | 2"]),
("Month-end", "Expenses by account for the year?", SQL,
 "SELECT l.gl_account, ROUND(SUM(l.functional_amount),2) FROM line_items l JOIN invoices i USING (vendor, invoice_no) WHERE i.date LIKE '2026%' GROUP BY 1 ORDER BY 1",
 ["1400 Prepaid Expenses | 2400.0", "5100 Dental Supplies | 2865.0", "6100 Accounting & Bookkeeping | 1900.0", "6150 Payroll Services | 950.0", "6200 Rent | 8000.0"]),
("Month-end", "What did we spend on payroll processing this year?", SQL,
 "SELECT ROUND(SUM(l.amount),2) FROM line_items l JOIN invoices i USING (vendor, invoice_no) WHERE l.gl_account LIKE '6150%' AND i.date LIKE '2026%'", ["950.0"]),
("Month-end", "What did we pay during September for August bills?", SQL,
 "SELECT a.invoice_no, a.amount FROM payment_applications a JOIN payments p USING (vendor, payment_id) JOIN invoices i ON i.vendor = a.vendor AND i.invoice_no = a.invoice_no WHERE p.date LIKE '2026-09%' AND i.date LIKE '2026-08%'",
 ["INV-0901 | 1400.0"]),

# J. Audit trail --------------------------------------------------------------------------------
("Audit", "Which file did INV-1001 come from?", SQL,
 "SELECT source_file, file FROM records WHERE number = 'INV-1001'", ["inv-1001.pdf", "INV-1001.md"]),
("Audit", "Show me every document for Acme.", SQL,
 "SELECT record_type, number FROM records WHERE vendor = 'Acme Bookkeeping' ORDER BY 1, 2",
 ["contract | ACME-2026-BOOKKEEPING", "invoice | INV-0815", "invoice | INV-1001", "payment | ACH-0930", "purchase_order | PO-5001"]),
("Audit", "As of what date are these numbers?", SQL,
 "SELECT as_of FROM settings", [AS_OF]),
# M. Month-end close & controls -------------------------------------------------------------------
("Close", "What should we accrue this month?", SQL,
 "SELECT kind, amount FROM accruals", ["received not invoiced | 800.0", "expected contract charge | 4000.0"]),
("Close", "Which contract charges are missing an invoice?", SQL,
 "SELECT vendor, period, amount FROM accruals WHERE kind='expected contract charge'", ["Oak Street Properties", "4000.0"]),
("Close", "What has been received but not invoiced?", SQL,
 "SELECT vendor, amount FROM accruals WHERE kind='received not invoiced'", ["800.0"]),
("Close", "What's the prepaid amortization schedule?", SQL,
 "SELECT COUNT(*), SUM(amount) FROM prepaid_schedule", ["12 | 2400.0"]),
("Close", "Which periods are closed?", SQL,
 "SELECT period, status FROM periods ORDER BY period", ["2026-08 | closed", "2026-09 | closed", "2026-10 | open"]),
("Close", "Was anything entered into a closed period?", SQL, X+"'Closed period'", ["PDS-3420", "Jane Doe"]),
("Close", "Any cutoff problems?", SQL, X+"'Cutoff'", ["QB-77", "2026-08-31"]),
("Close", "What's posted to the GL versus only indexed here?", SQL, "SELECT COUNT(*) FROM not_posted", ["13"]),
# N. Controls -------------------------------------------------------------------------------------
("Controls", "Was everything billed actually received?", SQL, X+"'Not received'", ["PO-7001", "received qty 3"]),
("Controls", "Who approved INV-1001?", SQL,
 "SELECT approver, role FROM approvals WHERE number='INV-1001'", ["Jane Doe | manager"]),
("Controls", "Did anyone approve over their limit?", SQL, X+"'Over approval limit'", ["Sam Lee", "RENT-1001"]),
("Controls", "Any segregation-of-duties problems?", SQL, X+"'Segregation of duties'", ["Jane Doe", "PDS-3301"]),
("Controls", "Did any vendor change bank details recently?", SQL, X+"'Bank change'", ["Pacific Dental Supply", "2026-09-25"]),
("Controls", "Are we paying any inactive vendors?", SQL, X+"'Inactive vendor'", ["Amazon Web Services"]),
("Controls", "What are our 1099 totals?", SQL,
 "SELECT vendor, box_1099, w9_on_file, paid FROM vendor_1099", ["Acme Bookkeeping | NEC-1 | yes | 3300.0", "Oak Street Properties | MISC-1 | no | 8100.0"]),
("Controls", "Which 1099 vendors are missing a W-9?", SQL, X+"'Missing W-9'", ["Oak Street Properties"]),
("Controls", "Are we billed above contract rates?", SQL,
 "SELECT invoice_no, variance_total FROM contract_price_variance WHERE variance_total > 0", ["INV-1001 | 50.0", "PDS-3301 | 50.0"]),
# O. Cash & bank ----------------------------------------------------------------------------------
("Cash", "Which checks are outstanding?", SQL, "SELECT payment_id, amount FROM outstanding_payments", ["CHK-2002 | 1100.0"]),
("Cash", "Did CHK-2001 clear the bank?", SQL, "SELECT status FROM payment_status WHERE payment_id='CHK-2001'", ["cleared"]),
("Cash", "Anything on the bank statement we haven't recorded?", SQL, X+"'Unrecorded bank transaction'", ["MONTHLY SERVICE FEE", "-35.00"]),
("Cash", "What vendor credits do we have?", SQL,
 "SELECT reference, credit, kind FROM vendor_credits", ["RENT-1001 | 100.0 | overpayment", "PDS-CM-3301 | 100.0 | credit memo"]),
("Cash", "Any unapplied payments?", SQL, "SELECT COUNT(*) FROM unapplied_payments", ["0"]),
("Cash", "How much cash do we need over the next 8 weeks?", SQL,
 "SELECT ROUND(SUM(amount),2) FROM cash_requirements", ["9910.3"]),
("Cash", "Which early-pay discounts did we miss or can still take?", SQL,
 "SELECT invoice_no, discount_amount, status FROM discounts", ["PDS-3301 | 24.0 | missed", "PDS-3420 | 6.0 | available"]),
# P. Budget, tax & FX ----------------------------------------------------------------------------
("Budget", "Are we over budget?", SQL,
 "SELECT period, gl_number, budget, actual, variance FROM budget_vs_actual", ["2026-09 | 5100 | 1800.0 | 2325.0 | 525.0", "2026-10 | 6400 | 150.0 | 120.0 | -30.0"]),
("Budget", "What's the Nordic Dental invoice in dollars?", SQL,
 "SELECT invoice_no, functional_amount, tax_amount FROM invoices WHERE vendor='Nordic Dental'", ["NDA-77 | 583.2 | 40.0"]),
("Budget", "Why isn't NDA-78 loaded?", SQL, "SELECT reason FROM review_queue WHERE file='NDA-78.md'", ["no fx_rate"]),
]

# ---------------------------------------------------------------- run
def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    shutil.copytree(HERE, tmp / "_system", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    shutil.copytree(HERE / "tests/fixture", tmp, dirs_exist_ok=True)
    for d in ("03_data", "04_graph"): (tmp / d).mkdir(exist_ok=True)
    env = {**os.environ, "INTEL_AS_OF": AS_OF}
    run = lambda *a: subprocess.run([sys.executable, *a], cwd=tmp, env=env, capture_output=True, text=True)
    s = run("_system/standardize.py")
    status = run("_system/rebuild.py")
    if status.returncode:
        print(s.stdout, s.stderr, status.stdout, status.stderr); raise SystemExit("rebuild failed")
    db = sqlite3.connect(tmp / "03_data/invoices.db")

    fails, areas = [], {}
    for n, (area, q, route, arg, expect) in enumerate(Q, 1):
        try:
            if route == SQL:
                rows = db.execute(arg).fetchall()
                out = "\n".join(" | ".join(str(c) for c in r) for r in rows) or "(no rows)"
            elif route == GRAPH: out = run("_system/graph.py", *arg).stdout
            elif route == STATUS: out = status.stdout
            elif route == INBOX: out = run("_system/inbox.py").stdout
            elif route == START: out = run("_system/start.py").stdout
            elif route == START_NEW:  # a fresh copy with no client named
                fresh = pathlib.Path(tempfile.mkdtemp())
                shutil.copytree(tmp, fresh, dirs_exist_ok=True)
                st = fresh / "_shared/settings.md"
                st.write_text("\n".join("client:" if l.startswith("client:") else l for l in st.read_text().splitlines()))
                out = subprocess.run([sys.executable, "_system/start.py"], cwd=fresh, capture_output=True, text=True).stdout
                shutil.rmtree(fresh, ignore_errors=True)
            else: out = (tmp / arg).read_text(encoding="utf-8")
        except Exception as e:
            out = f"ERROR: {e}"
        missing = [e for e in expect if e.lower() not in out.lower()]
        ok = not missing and not out.startswith("ERROR")
        areas.setdefault(area, [0, 0]); areas[area][0] += ok; areas[area][1] += 1
        if not ok: fails.append((n, area, q, route, missing, out))
        if VERBOSE: print(f"{'PASS' if ok else 'FAIL'} {n:3}. {q}\n      " + out.strip().replace("\n", "\n      ")[:600])

    print(f"\n{'Area':15} passed")
    for a, (p, t) in areas.items(): print(f"{a:15} {p}/{t}")
    total = sum(t for _, t in areas.values()); passed = total - len(fails)
    print(f"\nScore: {passed}/{total}")
    for n, area, q, route, missing, out in fails:
        print(f"\nFAIL {n}. [{area}] {q}  (route: {route})\n  missing: {missing}\n  got: {out.strip()[:500]}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1

if __name__ == "__main__":
    raise SystemExit(main())
