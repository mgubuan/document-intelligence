"""Rebuild the database, graph, and exceptions report from the markdown records. Safe to run anytime.

Only approved records (needs_review: false) are loaded; flagged ones are listed in the review_queue table.
"Today" for aging, deadlines, and accruals is the real date, or INTEL_AS_OF=YYYY-MM-DD if set (used by the self-test).

Sections:
  1. read master lists (_shared/)        4. matching checks (exceptions)
  2. create the schema                    5. controller layer: 3-way match, periods, approvals, vendors,
  3. load every record                       bank, accruals, prepaids, cash requirements
                                          6. write outputs and print status
"""
import calendar, csv, datetime, os, pathlib, re, shutil, sqlite3, sys, tempfile
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "03_data/invoices.db"
TOL = 0.01
AS_OF = datetime.date.fromisoformat(os.environ.get("INTEL_AS_OF") or datetime.date.today().isoformat())

# ------------------------------------------------------------------ helpers
def parse(path):
    _, front, body = path.read_text(encoding="utf-8").split("---", 2)
    meta = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in front.strip().splitlines() if ":" in l)}
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in body.splitlines() if l.startswith("|")]
    return meta, rows[2:]  # skip header + divider

def tables(path):
    """Every markdown table in the body, as (header, rows). Contracts have more than one."""
    body = path.read_text(encoding="utf-8").split("---", 2)[2]
    out, cur = [], []
    for l in body.splitlines() + [""]:
        if l.startswith("|"): cur.append([c.strip() for c in l.strip().strip("|").split("|")])
        elif cur: out.append((cur[0], cur[2:])); cur = []
    return out

def shared_table(name):
    """A _shared/ markdown table as a list of dicts keyed by its header. Missing file = empty list."""
    p = ROOT / "_shared" / name
    if not p.exists(): return []
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("|")]
    if len(rows) < 2: return []
    head = [h.strip().lower() for h in rows[0]]
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in rows[2:]]

def setting(key, default=""):
    for l in (ROOT / "_shared/settings.md").read_text(encoding="utf-8").splitlines():
        if l.startswith(f"{key}:"): return l.split(":", 1)[1].strip() or default
    return default

def parse_date(x):
    try: return datetime.date.fromisoformat(str(x).strip()[:10])
    except ValueError: return None

def num(x):
    x = str(x if x is not None else "").replace(",", "").replace("$", "").strip()
    try: return float(x) if x not in ("", "UNKNOWN") else None
    except ValueError: return None

gl_number = lambda g: (g or "").split(" ")[0]
yes = lambda x: str(x).strip().lower() in ("yes", "y", "true", "1")
month_start = lambda d: d.replace(day=1)
month_end = lambda d: d.replace(day=calendar.monthrange(d.year, d.month)[1])
def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return datetime.date(d.year + y, m + 1, 1)
period_of = lambda p: parse_date(f"{p}-01") if re.fullmatch(r"\d{4}-\d{2}", p or "") else None

FUNCTIONAL = setting("functional_currency", "USD").upper()
LOOKBACK = int(setting("accrual_lookback_months", "3") or 3)

# ------------------------------------------------------------------ 1-2. schema
TMP = pathlib.Path(tempfile.mkdtemp()) / "invoices.db"   # build aside, copy into place: works on synced folders
db = sqlite3.connect(TMP)
db.execute("PRAGMA foreign_keys = ON")
db.executescript("""
-- Documents are unique per vendor + number (two vendors can both use "1001").
CREATE TABLE invoices(invoice_no TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, doc_type, client, date, due_date,
    total REAL NOT NULL, currency, po_no, file,
    service_start, service_end, posting_period,                       -- which period it belongs to
    tax_amount REAL, tax_type, freight REAL,                            -- tax and freight, part of total
    fx_rate REAL, functional_amount REAL,                               -- total in home currency
    discount_pct REAL, discount_days INTEGER,                           -- early-pay terms, e.g. 2/10 net 30
    department, class, location, project, entity,                       -- reporting dimensions
    PRIMARY KEY (vendor, invoice_no));
CREATE TABLE line_items(vendor TEXT NOT NULL, invoice_no TEXT NOT NULL, description, qty REAL, unit_price REAL, amount REAL, gl_account,
    gl_number, functional_amount REAL, department, class, location, project, entity,
    FOREIGN KEY (vendor, invoice_no) REFERENCES invoices(vendor, invoice_no));
CREATE TABLE purchase_orders(po_no TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, client, date,
    total REAL NOT NULL, currency, file, receipt_required, PRIMARY KEY (vendor, po_no));
CREATE TABLE po_lines(vendor TEXT NOT NULL, po_no TEXT NOT NULL, description, qty REAL, unit_price REAL, amount REAL, gl_account,
    FOREIGN KEY (vendor, po_no) REFERENCES purchase_orders(vendor, po_no));
CREATE TABLE receipts(receipt_id TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, client, po_no, date, file,
    PRIMARY KEY (vendor, receipt_id));
CREATE TABLE receipt_lines(vendor TEXT NOT NULL, receipt_id TEXT NOT NULL, po_no, description, qty_received REAL,
    FOREIGN KEY (vendor, receipt_id) REFERENCES receipts(vendor, receipt_id));
CREATE TABLE payments(payment_id TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, client, date,
    amount REAL NOT NULL, method, currency, file, fx_rate REAL, functional_amount REAL, void,
    PRIMARY KEY (vendor, payment_id));
-- One payment can cover several invoices. Checked in exceptions instead of a hard key (the invoice may be in review).
CREATE TABLE payment_applications(vendor TEXT NOT NULL, payment_id TEXT NOT NULL, invoice_no TEXT NOT NULL, amount REAL NOT NULL,
    FOREIGN KEY (vendor, payment_id) REFERENCES payments(vendor, payment_id));
CREATE TABLE contracts(contract_id TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, client, title, contract_type,
    effective_date, end_date, auto_renew, renewal_term, notice_days INTEGER, notice_deadline, payment_terms,
    billing_frequency, recurring_amount REAL, total_value REAL, currency, file, PRIMARY KEY (vendor, contract_id));
CREATE TABLE contract_terms(vendor TEXT NOT NULL, contract_id TEXT NOT NULL, term, value, section,
    FOREIGN KEY (vendor, contract_id) REFERENCES contracts(vendor, contract_id));
CREATE TABLE contract_rates(vendor TEXT NOT NULL, contract_id TEXT NOT NULL, description, unit_price REAL, unit,
    FOREIGN KEY (vendor, contract_id) REFERENCES contracts(vendor, contract_id));

-- Master data from _shared/
CREATE TABLE vendors(vendor PRIMARY KEY, legal_name, tax_id_last4, w9_on_file, is_1099, box_1099, default_terms,
    default_gl, remit_bank_last4, bank_changed_at, status);
CREATE TABLE accounts(gl_account PRIMARY KEY, gl_number, name, type, is_prepaid);
CREATE TABLE periods(period PRIMARY KEY, status, closed_by, closed_at);
CREATE TABLE approval_limits(role PRIMARY KEY, max_amount REAL);
CREATE TABLE budgets(period, gl_number, department, amount REAL);

-- Controls and bank
CREATE TABLE approvals(record_type, vendor, number, amount REAL, approver, role, approved_at, extracted_by, limit_applied REAL);
CREATE TABLE gl_sync(record_type, vendor, number, erp_id, posted_at, status);
CREATE TABLE bank_transactions(txn_id PRIMARY KEY, account, date, amount REAL, description, reference, cleared, matched_payment);
CREATE TABLE payment_status(vendor, payment_id, status, cleared_date, txn_id);

-- Built by this script from the tables above
CREATE TABLE accruals(kind, vendor, reference, period, amount REAL, detail);
CREATE TABLE prepaid_schedule(vendor, invoice_no, gl_account, period, amount REAL);
CREATE TABLE cash_requirements(week_start, source, vendor, reference, amount REAL);

-- Housekeeping, so status questions can be answered with SQL too.
CREATE TABLE settings(as_of TEXT, functional_currency TEXT);
CREATE TABLE records(record_type, vendor, number, vendor_raw, client, date, amount REAL, doc_type,
    human_approved, source_file, file);                                   -- every loaded document, one row each
CREATE TABLE review_queue(record_type, number, vendor_raw, reason, file);   -- flagged, NOT loaded
CREATE TABLE refused_duplicates(record_type, vendor, number, kept_file, refused_file);
CREATE TABLE exceptions(kind, detail);                     -- same as exceptions.md
CREATE TABLE deadlines(vendor, contract_id, title, notice_deadline, days_left INTEGER, end_date, status);

-- What's paid and what's still open, per invoice.
CREATE VIEW invoice_balances AS
  SELECT i.vendor, i.invoice_no, i.total, ROUND(COALESCE(SUM(a.amount), 0), 2) AS paid,
         ROUND(i.total - COALESCE(SUM(a.amount), 0), 2) AS open_balance,
         CASE WHEN COALESCE(SUM(a.amount), 0) = 0 THEN 'open'
              WHEN i.total - SUM(a.amount) > 0.01 THEN 'partial'
              WHEN i.total - SUM(a.amount) < -0.01 THEN 'overpaid' ELSE 'paid' END AS status
  FROM invoices i LEFT JOIN payment_applications a ON a.vendor = i.vendor AND a.invoice_no = i.invoice_no
  GROUP BY i.vendor, i.invoice_no;
-- Unpaid invoices by age, as of the settings date.
CREATE VIEW ap_aging AS
  SELECT b.vendor, b.invoice_no, i.date, i.due_date, b.total, b.paid, b.open_balance, b.status,
         i.currency, ROUND(b.open_balance * COALESCE(i.fx_rate, 1), 2) AS open_home,   -- open amount in home currency
         CAST(julianday((SELECT as_of FROM settings)) - julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) AS INTEGER) AS days_past_due,
         CASE WHEN julianday((SELECT as_of FROM settings)) <= julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) THEN 'current'
              WHEN julianday((SELECT as_of FROM settings)) - julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) <= 30 THEN '1-30'
              WHEN julianday((SELECT as_of FROM settings)) - julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) <= 60 THEN '31-60'
              WHEN julianday((SELECT as_of FROM settings)) - julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) <= 90 THEN '61-90'
              ELSE '90+' END AS bucket
  FROM invoice_balances b JOIN invoices i ON i.vendor = b.vendor AND i.invoice_no = b.invoice_no
  WHERE b.status IN ('open', 'partial') AND b.open_balance > 0;   -- credits are in vendor_credits, not aging
-- PO consumption: ordered vs billed vs remaining.
CREATE VIEW po_status AS
  SELECT p.vendor, p.po_no, p.date, p.total AS ordered, ROUND(COALESCE(SUM(i.total), 0), 2) AS billed,
         ROUND(p.total - COALESCE(SUM(i.total), 0), 2) AS remaining, COUNT(i.invoice_no) AS invoices,
         CASE WHEN COALESCE(SUM(i.total), 0) = 0 THEN 'open'
              WHEN p.total - SUM(i.total) > 0.01 THEN 'partly billed'
              WHEN p.total - SUM(i.total) < -0.01 THEN 'over-billed' ELSE 'fully billed' END AS status
  FROM purchase_orders p LEFT JOIN invoices i ON i.vendor = p.vendor AND i.po_no = p.po_no
  GROUP BY p.vendor, p.po_no;
-- Money paid out but not applied to any invoice.
CREATE VIEW unapplied_payments AS
  SELECT p.vendor, p.payment_id, p.date, p.amount, ROUND(COALESCE(SUM(a.amount), 0), 2) AS applied,
         ROUND(p.amount - COALESCE(SUM(a.amount), 0), 2) AS unapplied
  FROM payments p LEFT JOIN payment_applications a ON a.vendor = p.vendor AND a.payment_id = p.payment_id
  WHERE COALESCE(p.void, '') <> 'yes'
  GROUP BY p.vendor, p.payment_id HAVING ABS(p.amount - COALESCE(SUM(a.amount), 0)) > 0.01;
-- Credits sitting with vendors: open credit memos and overpayments.
CREATE VIEW vendor_credits AS
  SELECT b.vendor, b.invoice_no AS reference, -b.open_balance AS credit,
         CASE WHEN i.doc_type = 'credit memo' THEN 'credit memo' ELSE 'overpayment' END AS kind
  FROM invoice_balances b JOIN invoices i ON i.vendor = b.vendor AND i.invoice_no = b.invoice_no
  WHERE b.open_balance < -0.01;
-- Invoice line prices against the contract in force on the invoice date.
CREATE VIEW contract_price_variance AS
  SELECT i.vendor, i.invoice_no, i.date, l.description, l.qty, l.unit_price AS billed_price, r.unit_price AS contract_price,
         ROUND(l.unit_price - r.unit_price, 2) AS variance_per_unit, ROUND((l.unit_price - r.unit_price) * l.qty, 2) AS variance_total,
         c.contract_id
  FROM invoices i JOIN line_items l ON l.vendor = i.vendor AND l.invoice_no = i.invoice_no
  JOIN contracts c ON c.vendor = i.vendor AND i.date >= c.effective_date AND i.date <= COALESCE(c.end_date, '9999-12-31')
  JOIN contract_rates r ON r.vendor = c.vendor AND r.contract_id = c.contract_id AND LOWER(r.description) = LOWER(l.description)
  WHERE COALESCE(i.doc_type, '') <> 'credit memo' AND l.unit_price >= 0;   -- credits aren't prices
-- Budget vs actual by posting period, GL account number, and department (home currency).
CREATE VIEW budget_vs_actual AS
  WITH actual AS (
    SELECT i.posting_period AS period, l.gl_number, COALESCE(l.department, '') AS department, SUM(l.functional_amount) AS actual
    FROM line_items l JOIN invoices i ON i.vendor = l.vendor AND i.invoice_no = l.invoice_no GROUP BY 1, 2, 3)
  SELECT b.period, b.gl_number, b.department, b.amount AS budget,
         ROUND(COALESCE((SELECT SUM(a.actual) FROM actual a WHERE a.period = b.period AND a.gl_number = b.gl_number
                         AND (b.department = '' OR a.department = b.department)), 0), 2) AS actual,
         ROUND(COALESCE((SELECT SUM(a.actual) FROM actual a WHERE a.period = b.period AND a.gl_number = b.gl_number
                         AND (b.department = '' OR a.department = b.department)), 0) - b.amount, 2) AS variance
  FROM budgets b;
-- Early-pay discounts: captured (paid in full in time), missed, or still available.
CREATE VIEW discounts AS
  SELECT i.vendor, i.invoice_no, i.date, i.discount_pct, i.discount_days,
         date(i.date, '+' || i.discount_days || ' days') AS discount_deadline,
         ROUND(i.total * i.discount_pct / 100.0, 2) AS discount_amount,
         CASE WHEN (SELECT SUM(a.amount) FROM payment_applications a JOIN payments p ON p.vendor = a.vendor AND p.payment_id = a.payment_id
                    WHERE a.vendor = i.vendor AND a.invoice_no = i.invoice_no AND p.date <= date(i.date, '+' || i.discount_days || ' days'))
                   >= i.total * (1 - i.discount_pct / 100.0) - 0.01 THEN 'captured'
              WHEN date(i.date, '+' || i.discount_days || ' days') >= (SELECT as_of FROM settings) THEN 'available'
              ELSE 'missed' END AS status
  FROM invoices i WHERE COALESCE(i.discount_pct, 0) > 0;
-- Approved invoices that haven't been posted to the accounting system yet.
CREATE VIEW not_posted AS
  SELECT i.vendor, i.invoice_no, i.date, i.total FROM invoices i
  WHERE NOT EXISTS (SELECT 1 FROM gl_sync g WHERE g.record_type = 'invoice' AND g.vendor = i.vendor AND g.number = i.invoice_no
                    AND g.status = 'posted');
-- Checks and payments sent but not yet cleared the bank.
CREATE VIEW outstanding_payments AS
  SELECT s.vendor, s.payment_id, p.date, p.amount, p.method, s.status FROM payment_status s
  JOIN payments p ON p.vendor = s.vendor AND p.payment_id = s.payment_id WHERE s.status IN ('issued', 'stale');
-- 1099 totals by vendor for each calendar year (payments, home currency).
CREATE VIEW vendor_1099 AS
  SELECT v.vendor, substr(p.date, 1, 4) AS year, v.box_1099, v.w9_on_file, v.tax_id_last4,
         ROUND(SUM(COALESCE(p.functional_amount, p.amount)), 2) AS paid
  FROM vendors v JOIN payments p ON p.vendor = v.vendor
  WHERE LOWER(v.is_1099) = 'yes' AND COALESCE(p.void, '') <> 'yes' GROUP BY v.vendor, year;
""")
db.execute("INSERT INTO settings VALUES (?, ?)", (AS_OF.isoformat(), FUNCTIONAL))

# master data
for r in shared_table("vendors.md"):
    if not r.get("vendor"): continue
    db.execute("INSERT OR REPLACE INTO vendors VALUES (?,?,?,?,?,?,?,?,?,?,?)", (r["vendor"], r.get("legal_name"),
        r.get("tax_id_last4"), r.get("w9_on_file"), r.get("is_1099"), r.get("1099_box"), r.get("default_terms"),
        r.get("default_gl"), r.get("remit_bank_last4"), r.get("bank_changed_at"), r.get("status") or "active"))
PREPAID = set()
for r in shared_table("chart-of-accounts.md"):
    if not r.get("account"): continue
    db.execute("INSERT OR REPLACE INTO accounts VALUES (?,?,?,?,?)", (r["account"], gl_number(r["account"]),
        r["account"].split(" ", 1)[-1], r.get("type") or "expense", r.get("is_prepaid") or "no"))
    if yes(r.get("is_prepaid")): PREPAID.add(r["account"])
PERIODS = {}
for r in shared_table("periods.md"):
    if r.get("period"):
        PERIODS[r["period"]] = r
        db.execute("INSERT OR REPLACE INTO periods VALUES (?,?,?,?)", (r["period"], r.get("status") or "open", r.get("closed_by"), r.get("closed_at")))
LIMITS = {r["role"].lower(): num(r.get("max_amount")) for r in shared_table("approval-limits.md") if r.get("role")}
db.executemany("INSERT INTO approval_limits VALUES (?,?)", LIMITS.items())
for r in shared_table("budgets.md"):
    if r.get("period") and num(r.get("amount")) is not None:
        db.execute("INSERT INTO budgets VALUES (?,?,?,?)", (r["period"], gl_number(r.get("gl_account")), r.get("department") or "", num(r["amount"])))

# ------------------------------------------------------------------ 3. load records
ID_FIELD = {"invoice": "invoice_no", "purchase_order": "po_no", "payment": "payment_id", "contract": "contract_id", "receipt": "receipt_id"}
triples, flagged, dupes, loaded, X = [], [], [], {}, []
counts = Counter()

def fx(m, amount):
    """(rate, home-currency amount). Same currency = 1.0. Missing rate on a foreign document = None."""
    cur = (m.get("currency") or FUNCTIONAL).upper()
    rate = 1.0 if cur == FUNCTIONAL else num(m.get("fx_rate"))
    return rate, (round(amount * rate, 2) if rate is not None and amount is not None else None)

# shortest name first, so the original "INV-1001.md" wins over "INV-1001-copy.md" when duplicates arrive
for f in sorted((ROOT / "02_extracted").glob("*.md"), key=lambda p: (len(p.name), p.name)):
    if f.name.startswith("_") or f.name == "CONTEXT.md":
        continue
    m, rows = parse(f)
    rtype = m.get("record_type", "invoice")
    if rtype not in ID_FIELD:
        print(f"Skipped {f.name}: unknown record_type '{rtype}'"); continue
    if "vendor" not in m:
        raise SystemExit(f"{f.name} isn't standardized yet - run: python _system/standardize.py")
    rid = m.get(ID_FIELD[rtype])
    if m.get("needs_review") == "true":
        flagged.append(f"{rtype} {rid} ({m.get('review_reason', '')})")
        db.execute("INSERT INTO review_queue VALUES (?,?,?,?,?)", (rtype, rid, m.get("vendor_raw"), m.get("review_reason"), f.name))
        continue
    v, key = m["vendor"], (rtype, m["vendor"], rid)
    node = f"{v}/{rid}"  # graph node name matches the database key
    dims = [m.get(k) or None for k in ("department", "class", "location", "project", "entity")]
    try:
        if rtype == "invoice":
            total = num(m["total"])
            rate, home = fx(m, total)
            period = m.get("posting_period") or (m.get("date") or "")[:7]
            db.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, v, m["vendor_raw"],
                m.get("doc_type"), m.get("client"), m.get("date"), m.get("due_date"), total, m.get("currency"), m.get("po_no") or None,
                f.name, m.get("service_start") or None, m.get("service_end") or None, period, num(m.get("tax_amount")),
                m.get("tax_type") or None, num(m.get("freight")), rate, home, num(m.get("discount_pct")),
                int(num(m.get("discount_days")) or 0) or None, *dims))
            rows = [r for r in rows if len(r) == 5]
            db.executemany("INSERT INTO line_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(v, rid, r[0], num(r[1]), num(r[2]), num(r[3]), r[4], gl_number(r[4]),
                  round(num(r[3]) * rate, 2) if rate is not None and num(r[3]) is not None else None, *dims) for r in rows])
            triples += [(v, "billed", m["client"]), (v, "issued", node), (node, "billed_to", m["client"]),
                        (node, "dated", m["date"][:7]), (node, "is_a", m.get("doc_type"))]
            triples += [(node, "includes", r[0]) for r in rows] + [(r[0], "coded_to", r[4]) for r in rows]
            if m.get("po_no"): triples.append((node, "bills_against", f"{v}/{m['po_no']}"))
        elif rtype == "purchase_order":
            db.execute("INSERT INTO purchase_orders VALUES (?,?,?,?,?,?,?,?,?)", (rid, v, m["vendor_raw"], m.get("client"),
                       m.get("date"), m["total"], m.get("currency"), f.name, m.get("receipt_required") or "yes"))
            rows = [r for r in rows if len(r) == 5]
            db.executemany("INSERT INTO po_lines VALUES (?,?,?,?,?,?,?)", [(v, rid, *r) for r in rows])
            triples += [(m["client"], "ordered_from", v), (node, "ordered_by", m["client"]), (node, "ordered_from", v),
                        (node, "dated", m["date"][:7])]
            triples += [(node, "includes", r[0]) for r in rows] + [(r[0], "coded_to", r[4]) for r in rows]
        elif rtype == "receipt":
            db.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,?)", (rid, v, m["vendor_raw"], m.get("client"),
                       m.get("po_no") or None, m.get("date"), f.name))
            rows = [r for r in rows if len(r) >= 2 and num(r[1]) is not None]
            db.executemany("INSERT INTO receipt_lines VALUES (?,?,?,?,?)", [(v, rid, m.get("po_no") or None, r[0], num(r[1])) for r in rows])
            triples += [(node, "received_from", v), (node, "dated", m["date"][:7])]
            if m.get("po_no"): triples.append((node, "received_against", f"{v}/{m['po_no']}"))
        elif rtype == "contract":
            eff, end = parse_date(m.get("effective_date")), parse_date(m.get("end_date"))
            nd = m.get("notice_days", "").strip()
            deadline = (end - datetime.timedelta(days=int(nd))).isoformat() if end and nd.isdigit() else None
            db.execute("INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, v, m["vendor_raw"],
                m.get("client"), m.get("title"), m.get("contract_type"), eff and eff.isoformat(), end and end.isoformat(),
                m.get("auto_renew"), m.get("renewal_term"), int(nd) if nd.isdigit() else None, deadline,
                m.get("payment_terms"), m.get("billing_frequency"), num(m.get("recurring_amount", "")),
                num(m.get("total_value", "")), m.get("currency"), f.name))
            for head, trows in tables(f):
                if head and head[0].lower() == "term":
                    db.executemany("INSERT INTO contract_terms VALUES (?,?,?,?,?)", [(v, rid, *(r + ["", "", ""])[:3]) for r in trows])
                elif head and head[0].lower() == "description":
                    db.executemany("INSERT INTO contract_rates VALUES (?,?,?,?,?)",
                                   [(v, rid, r[0], num(r[1]), (r + [""])[2]) for r in trows if len(r) >= 2 and num(r[1]) is not None])
                    triples += [(node, "sets_rate_for", r[0]) for r in trows if r]
            triples += [(node, "contract_with", v), (m["client"], "has_contract", node), (node, "is_a", m.get("contract_type"))]
            if end: triples.append((node, "ends", end.isoformat()[:7]))
            if m.get("auto_renew") == "yes": triples.append((node, "auto_renews", m.get("renewal_term") or "yes"))
        else:  # payment
            amount = num(m["amount"])
            rate, home = fx(m, amount)
            db.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (rid, v, m["vendor_raw"], m.get("client"),
                       m.get("date"), amount, m.get("method"), m.get("currency"), f.name, rate, home,
                       "yes" if (m.get("status") or "").lower() == "void" else None))
            rows = [r for r in rows if len(r) >= 2 and num(r[1]) is not None]
            db.executemany("INSERT INTO payment_applications VALUES (?,?,?,?)", [(v, rid, r[0], num(r[1])) for r in rows])
            triples += [(m["client"], "paid", v), (node, "paid_to", v), (node, "dated", m["date"][:7])]
            triples += [(node, "pays", f"{v}/{r[0]}") for r in rows]
    except sqlite3.IntegrityError:
        dupes.append(f"{rtype} {v} {rid}: kept {loaded[key]}, refused {f.name}")
        db.execute("INSERT INTO refused_duplicates VALUES (?,?,?,?,?)", (rtype, v, rid, loaded[key], f.name)); continue
    loaded[key] = f.name
    amount = num(m.get("total") or m.get("amount") or m.get("total_value") or "")
    db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)", (rtype, v, rid, m.get("vendor_raw"), m.get("client"),
               m.get("date") or m.get("effective_date"), amount, m.get("doc_type"), m.get("approved_by_human") == "true",
               m.get("source_file"), f.name))
    if m.get("approved_by"):   # who approved, in what role, with what limit
        role = (m.get("approver_role") or "").lower()
        db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?)", (rtype, v, rid, amount, m["approved_by"], role,
                   m.get("approved_at"), m.get("extracted_by"), LIMITS.get(role)))
    if m.get("erp_id") or m.get("gl_status"):
        db.execute("INSERT INTO gl_sync VALUES (?,?,?,?,?,?)", (rtype, v, rid, m.get("erp_id"), m.get("posted_at"),
                   (m.get("gl_status") or "posted").lower()))
    if rtype == "invoice" and m.get("extracted_on"):
        period = m.get("posting_period") or (m.get("date") or "")[:7]
        p = PERIODS.get(period, {})
        closed_at = parse_date(p.get("closed_at"))
        if (p.get("status") or "").lower() == "closed" and closed_at and (parse_date(m["extracted_on"]) or AS_OF) > closed_at:
            X.append(f"Closed period: {v} {rid} was entered on {m['extracted_on']} into {period}, "
                     f"which {p.get('closed_by') or 'someone'} closed on {p.get('closed_at')}.")
    counts[rtype] += 1

# bank statements: 02_extracted/BANK-*.csv  (txn_id, account, date, amount, description, reference)
for f in sorted((ROOT / "02_extracted").glob("BANK-*.csv")):
    for r in csv.DictReader(open(f, encoding="utf-8-sig")):
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        if r.get("txn_id") and num(r.get("amount")) is not None:
            db.execute("INSERT OR IGNORE INTO bank_transactions VALUES (?,?,?,?,?,?,?,?)", (r["txn_id"], r.get("account"),
                       r.get("date"), num(r["amount"]), r.get("description"), r.get("reference"), "no", None))
            counts["bank"] += 1

# ------------------------------------------------------------------ 4. matching checks: reported, never blocking
for v, inv, po in db.execute("""SELECT i.vendor, i.invoice_no, i.po_no FROM invoices i
        LEFT JOIN purchase_orders p ON p.vendor = i.vendor AND p.po_no = i.po_no
        WHERE i.po_no IS NOT NULL AND p.po_no IS NULL"""):
    X.append(f"Invoice {v} {inv} references PO {po}, which isn't loaded (missing, or still in review).")
for v, po, pototal, billed, invs in db.execute("""SELECT p.vendor, p.po_no, p.total, ROUND(SUM(i.total), 2), GROUP_CONCAT(i.invoice_no, ', ')
        FROM purchase_orders p JOIN invoices i ON i.vendor = p.vendor AND i.po_no = p.po_no
        GROUP BY p.vendor, p.po_no HAVING SUM(i.total) > p.total + ?""", (TOL,)):
    X.append(f"Over-billed: {v} PO {po} is for {pototal:.2f}, but invoices {invs} total {billed:.2f}.")
for v, pid, inv, amt in db.execute("""SELECT a.vendor, a.payment_id, a.invoice_no, a.amount FROM payment_applications a
        LEFT JOIN invoices i ON i.vendor = a.vendor AND i.invoice_no = a.invoice_no WHERE i.invoice_no IS NULL"""):
    X.append(f"Payment {v} {pid} applies {amt:.2f} to invoice {inv}, which isn't loaded (missing, or still in review).")
for v, inv, total, paid in db.execute("SELECT vendor, invoice_no, total, paid FROM invoice_balances WHERE status = 'overpaid'"):
    X.append(f"Overpaid: {v} {inv} is for {total:.2f}, but {paid:.2f} has been applied.")

# contracts: billing outside the term, rates above the contract, spend above the contract value
IN_TERM = "i.date >= c.effective_date AND i.date <= COALESCE(c.end_date, '9999-12-31')"
for v, inv, d in db.execute(f"""SELECT i.vendor, i.invoice_no, i.date FROM invoices i
        WHERE EXISTS (SELECT 1 FROM contracts c WHERE c.vendor = i.vendor)
          AND NOT EXISTS (SELECT 1 FROM contracts c WHERE c.vendor = i.vendor AND {IN_TERM})"""):
    X.append(f"Outside contract: {v} {inv} is dated {d}, outside every contract term on file for {v}.")
for v, inv, desc, billed, agreed, ctr in db.execute("""SELECT vendor, invoice_no, description, billed_price, contract_price, contract_id
        FROM contract_price_variance WHERE variance_per_unit > ?""", (TOL,)):
    X.append(f"Above contract rate: {v} {inv} bills '{desc}' at {billed:.2f}; contract {ctr} says {agreed:.2f}.")
for v, ctr, cap, spent in db.execute(f"""SELECT c.vendor, c.contract_id, c.total_value, ROUND(SUM(i.total), 2)
        FROM contracts c JOIN invoices i ON i.vendor = c.vendor AND {IN_TERM}
        WHERE c.total_value IS NOT NULL GROUP BY c.vendor, c.contract_id HAVING SUM(i.total) > c.total_value + ?""", (TOL,)):
    X.append(f"Over contract value: {v} {ctr} is capped at {cap:.2f}; invoices in its term total {spent:.2f}.")
for inv_v, inv, ctr in db.execute(f"""SELECT i.vendor, i.invoice_no, c.contract_id FROM invoices i
        JOIN contracts c ON c.vendor = i.vendor AND {IN_TERM}"""):
    triples.append((f"{inv_v}/{inv}", "under_contract", f"{inv_v}/{ctr}"))

# ------------------------------------------------------------------ 5. controller layer
# 3-way match: what was billed vs what was received, per PO line
received = defaultdict(float)
for v, po, desc, q in db.execute("SELECT vendor, po_no, LOWER(description), SUM(qty_received) FROM receipt_lines GROUP BY 1, 2, 3"):
    received[(v, po, desc)] = q
billed_qty = defaultdict(float)
for v, po, desc, q in db.execute("""SELECT i.vendor, i.po_no, LOWER(l.description), SUM(l.qty) FROM invoices i
        JOIN line_items l ON l.vendor = i.vendor AND l.invoice_no = i.invoice_no WHERE i.po_no IS NOT NULL GROUP BY 1, 2, 3"""):
    billed_qty[(v, po, desc)] = q
for v, po, req in db.execute("SELECT vendor, po_no, receipt_required FROM purchase_orders"):
    has_inv = db.execute("SELECT GROUP_CONCAT(invoice_no, ', ') FROM invoices WHERE vendor = ? AND po_no = ?", (v, po)).fetchone()[0]
    has_rcv = db.execute("SELECT COUNT(*) FROM receipts WHERE vendor = ? AND po_no = ?", (v, po)).fetchone()[0]
    if not yes(req or "yes") or not has_inv: continue
    if not has_rcv:
        X.append(f"No receipt: {v} PO {po} has been billed ({has_inv}) but nothing has been received against it.")
        continue
    for (bv, bpo, desc), q in billed_qty.items():
        if (bv, bpo) == (v, po) and q > received.get((v, po, desc), 0) + 1e-9:
            X.append(f"Not received: {v} PO {po} '{desc}' billed qty {q:g}, received qty {received.get((v, po, desc), 0):g}.")

# cutoff: service period vs posting period
for v, inv, start, end, period, gls in db.execute("""SELECT i.vendor, i.invoice_no, i.service_start, i.service_end, i.posting_period,
        GROUP_CONCAT(l.gl_account, '|') FROM invoices i JOIN line_items l ON l.vendor = i.vendor AND l.invoice_no = i.invoice_no
        WHERE i.service_start IS NOT NULL OR i.service_end IS NOT NULL GROUP BY 1, 2"""):
    p0 = period_of(period)
    if not p0: continue
    s, e = parse_date(start), parse_date(end)
    prepaid = any(g in PREPAID for g in (gls or "").split("|"))
    if e and e < p0:
        X.append(f"Cutoff: {v} {inv} is for service ending {end} but is posted to {period}; it belongs to an earlier period.")
    elif s and s > month_end(p0) and not prepaid:
        X.append(f"Cutoff: {v} {inv} is for service starting {start} but is posted to {period} as an expense; "
                 f"it should be prepaid or posted later.")

# prepaid amortization: invoices coded to prepaid accounts, spread evenly over their service months
for v, inv, gl, amt, start, end in db.execute("""SELECT l.vendor, l.invoice_no, l.gl_account, SUM(l.functional_amount), i.service_start, i.service_end
        FROM line_items l JOIN invoices i ON i.vendor = l.vendor AND i.invoice_no = l.invoice_no GROUP BY 1, 2, 3"""):
    if gl not in PREPAID: continue
    s, e = parse_date(start), parse_date(end)
    if not (s and e and amt):
        X.append(f"Prepaid without service period: {v} {inv} is coded to {gl} but has no service_start/service_end.")
        continue
    months = []
    d = month_start(s)
    while d <= e: months.append(d); d = add_months(d, 1)
    each = round(amt / len(months), 2)
    for i, d in enumerate(months):
        last = i == len(months) - 1
        db.execute("INSERT INTO prepaid_schedule VALUES (?,?,?,?,?)", (v, inv, gl, d.strftime("%Y-%m"),
                   round(amt - each * (len(months) - 1), 2) if last else each))

# approvals: over the approver's limit, and approving your own work
for rtype, v, number, amount, who, role, extracted_by, limit in db.execute(
        "SELECT record_type, vendor, number, amount, approver, role, extracted_by, limit_applied FROM approvals"):
    if not role or limit is None:
        X.append(f"Over approval limit: {who} approved {v} {number} as '{role or 'no role'}', which has no limit in approval-limits.md.")
    elif amount is not None and amount > limit + TOL:
        X.append(f"Over approval limit: {who} ({role}, limit {limit:.2f}) approved {v} {number} for {amount:.2f}.")
    if extracted_by and who and who.strip().lower() == extracted_by.strip().lower():
        X.append(f"Segregation of duties: {who} both extracted and approved {v} {number}.")

# vendor master checks
for v, d in db.execute("""SELECT DISTINCT i.vendor, i.date FROM invoices i JOIN vendors m ON m.vendor = i.vendor
        WHERE LOWER(m.status) = 'inactive'"""):
    X.append(f"Inactive vendor: {v} billed on {d} but is marked inactive in vendors.md.")
for v, pid, d, changed in db.execute("""SELECT p.vendor, p.payment_id, p.date, v.bank_changed_at FROM payments p
        JOIN vendors v ON v.vendor = p.vendor WHERE COALESCE(v.bank_changed_at, '') <> ''
        AND julianday(p.date) >= julianday(v.bank_changed_at) AND julianday(p.date) - julianday(v.bank_changed_at) <= 30"""):
    X.append(f"Bank change: {v} {pid} paid on {d}, within 30 days of the vendor's bank details changing on {changed}. "
             f"Confirm the change by phone before paying again.")
for v, year, paid in db.execute("SELECT vendor, year, paid FROM vendor_1099 WHERE paid >= 600 AND LOWER(COALESCE(w9_on_file, '')) <> 'yes'"):
    X.append(f"Missing W-9: {v} is a 1099 vendor paid {paid:.2f} in {year} with no W-9 on file.")

# FX: foreign documents without a rate (standardize flags these; this catches approved_by_human overrides)
for v, inv, cur in db.execute("SELECT vendor, invoice_no, currency FROM invoices WHERE fx_rate IS NULL"):
    X.append(f"Missing FX rate: {v} {inv} is in {cur} with no fx_rate, so it is left out of home-currency totals.")

# bank: match payments to bank transactions (reference first, then amount within 7 days)
bank = db.execute("SELECT txn_id, date, amount, reference, description FROM bank_transactions ORDER BY date").fetchall()
window = (min((parse_date(b[1]) for b in bank), default=None), max((parse_date(b[1]) for b in bank), default=None))
used = set()
digits = lambda s: re.sub(r"\D", "", s or "")
for v, pid, d, amount, void in db.execute("SELECT vendor, payment_id, date, amount, void FROM payments ORDER BY date").fetchall():
    pd = parse_date(d)
    if void == "yes":
        db.execute("INSERT INTO payment_status VALUES (?,?,?,?,?)", (v, pid, "void", None, None)); continue
    hit = None
    for t in bank:  # reference match: the check or transfer number appears on the bank line
        if t[0] in used or abs(abs(t[2]) - amount) > TOL: continue
        if digits(pid) and digits(pid)[-4:] and digits(pid)[-4:] in digits(t[3] or "") + digits(t[4] or ""): hit = t; break
    if not hit:
        for t in bank:  # amount within 7 days on or after the payment date
            td = parse_date(t[1])
            if t[0] in used or abs(abs(t[2]) - amount) > TOL or t[2] > 0 or not (td and pd): continue
            if 0 <= (td - pd).days <= 7: hit = t; break
    if hit:
        used.add(hit[0])
        db.execute("UPDATE bank_transactions SET cleared = 'yes', matched_payment = ? WHERE txn_id = ?", (f"{v}/{pid}", hit[0]))
        db.execute("INSERT INTO payment_status VALUES (?,?,?,?,?)", (v, pid, "cleared", hit[1], hit[0]))
    elif not window[0] or not pd or pd < window[0]:
        db.execute("INSERT INTO payment_status VALUES (?,?,?,?,?)", (v, pid, "no bank data", None, None))
    else:
        db.execute("INSERT INTO payment_status VALUES (?,?,?,?,?)", (v, pid, "stale" if (AS_OF - pd).days > 90 else "issued", None, None))
for txn, d, amount, desc in db.execute("SELECT txn_id, date, amount, description FROM bank_transactions WHERE cleared = 'no' AND amount < 0"):
    X.append(f"Unrecorded bank transaction: {txn} on {d}, {amount:.2f} '{desc}' has no matching payment record.")

# accruals 1: received but not invoiced, valued at the PO price
for v, rid, po, desc, q, d in db.execute("""SELECT r.vendor, GROUP_CONCAT(DISTINCT r.receipt_id), r.po_no, l.description, SUM(l.qty_received), MAX(r.date)
        FROM receipts r JOIN receipt_lines l ON l.vendor = r.vendor AND l.receipt_id = r.receipt_id
        GROUP BY r.vendor, r.po_no, LOWER(l.description)""").fetchall():
    open_q = q - billed_qty.get((v, po, desc.lower()), 0)
    if open_q <= 1e-9: continue
    price = db.execute("SELECT unit_price FROM po_lines WHERE vendor = ? AND po_no = ? AND LOWER(description) = LOWER(?)", (v, po, desc)).fetchone()
    amt = round(open_q * price[0], 2) if price and price[0] is not None else None
    db.execute("INSERT INTO accruals VALUES (?,?,?,?,?,?)", ("received not invoiced", v, f"{po} / {rid}", d[:7], amt,
               f"{open_q:g} x '{desc}' received {d}, not yet invoiced" + ("" if amt is not None else " (no PO price to value it)")))

# accruals 2: recurring contract charges expected in recent completed months but never invoiced
def covered(v, month):
    lo, hi = month.isoformat(), month_end(month).isoformat()
    return db.execute("""SELECT 1 FROM invoices WHERE vendor = ? AND (posting_period = ? OR
        (service_start IS NOT NULL AND service_start <= ? AND COALESCE(service_end, service_start) >= ?) OR
        (service_start IS NULL AND date BETWEEN ? AND ?)) LIMIT 1""", (v, month.strftime("%Y-%m"), hi, lo, lo, hi)).fetchone()
for v, ctr, freq, amt, eff, end in db.execute("""SELECT vendor, contract_id, LOWER(billing_frequency), recurring_amount, effective_date, end_date
        FROM contracts WHERE recurring_amount IS NOT NULL""").fetchall():
    if freq != "monthly": continue
    for k in range(LOOKBACK, 0, -1):
        mth = add_months(month_start(AS_OF), -k)
        if (eff and parse_date(eff) > month_end(mth)) or (end and parse_date(end) < mth): continue
        if not covered(v, mth):
            db.execute("INSERT INTO accruals VALUES (?,?,?,?,?,?)", ("expected contract charge", v, ctr, mth.strftime("%Y-%m"), amt,
                       f"{ctr} bills {amt:.2f} monthly; no invoice found for {mth.strftime('%Y-%m')}"))

# cash requirements: open AP by the week it's due (overdue = this week), plus recurring contract charges, next 8 weeks
week = lambda d: (d - datetime.timedelta(days=d.weekday())).isoformat()
horizon = AS_OF + datetime.timedelta(weeks=8)
for v, inv, due, amt in db.execute("""SELECT a.vendor, a.invoice_no, COALESCE(NULLIF(a.due_date, ''), a.date),
        ROUND(a.open_balance * COALESCE(i.fx_rate, 1), 2) FROM ap_aging a
        JOIN invoices i ON i.vendor = a.vendor AND i.invoice_no = a.invoice_no""").fetchall():   # home currency
    dd = max(parse_date(due) or AS_OF, AS_OF)
    if dd <= horizon: db.execute("INSERT INTO cash_requirements VALUES (?,?,?,?,?)", (week(dd), "open invoice", v, inv, amt))
for v, ctr, amt, eff, end in db.execute("""SELECT vendor, contract_id, recurring_amount, effective_date, end_date FROM contracts
        WHERE recurring_amount IS NOT NULL AND LOWER(billing_frequency) = 'monthly'""").fetchall():
    d = add_months(month_start(AS_OF), 1)
    while d <= horizon:
        if not ((eff and parse_date(eff) > d) or (end and parse_date(end) < d)):
            db.execute("INSERT INTO cash_requirements VALUES (?,?,?,?,?)", (week(d), "contract commitment", v, ctr, amt))
        d = add_months(d, 1)

# deadlines: notice dates coming up in the next 90 days (or missed, before the contract ends)
today = AS_OF
D = []
for v, ctr, title, end, deadline, ar, term in db.execute("""SELECT vendor, contract_id, title, end_date, notice_deadline,
        auto_renew, renewal_term FROM contracts WHERE notice_deadline IS NOT NULL ORDER BY notice_deadline""").fetchall():
    dl, en = datetime.date.fromisoformat(deadline), datetime.date.fromisoformat(end)
    days = (dl - today).days
    what = f"it auto-renews for {term}" if ar == "yes" else "it ends"
    status = "upcoming" if 0 <= days <= 90 else "missed" if days < 0 <= (en - today).days else "later" if days > 90 else "ended"
    db.execute("INSERT INTO deadlines VALUES (?,?,?,?,?,?,?)", (v, ctr, title, deadline, days, end, status))
    if status == "upcoming":
        D.append(f"{deadline} ({days} days): last day to give notice on {v} {ctr} ({title}), or {what} on {end}.")
    elif status == "missed":
        D.append(f"MISSED {deadline}: notice window for {v} {ctr} closed; {what} on {end}.")

KINDS = {"Over-billed", "Overpaid", "Outside contract", "Above contract rate", "Over contract value", "No receipt",
         "Not received", "Closed period", "Cutoff", "Prepaid without service period", "Over approval limit",
         "Segregation of duties", "Inactive vendor", "Bank change", "Missing W-9", "Missing FX rate", "Unrecorded bank transaction"}
db.executemany("INSERT INTO exceptions VALUES (?,?)", [(x.split(":")[0] if x.split(":")[0] in KINDS else "Missing link", x) for x in X])
A = db.execute("SELECT kind, vendor, reference, period, amount, detail FROM accruals ORDER BY period, vendor").fetchall()

db.commit()
db.close()
shutil.copyfile(TMP, DB)

# ------------------------------------------------------------------ 6. outputs
(ROOT / "03_data/exceptions.md").write_text(
    "# Exceptions\n\nGenerated by rebuild.py - do not edit. Fix the records, then rebuild.\n\n"
    + ("\n".join(f"- {x}" for x in X) if X else "None. Everything matches.")
    + "\n\n## Contract deadlines (next 90 days)\n\n" + ("\n".join(f"- {x}" for x in D) if D else "None.")
    + "\n\n## Accruals to consider (unrecorded liabilities)\n\n"
    + ("\n".join(f"- {k}: {v} {r} ({p}) {('%.2f' % a) if a is not None else '?'} — {d}" for k, v, r, p, a, d in A) if A else "None.")
    + "\n", encoding="utf-8")

edges = Counter(triples)  # each edge once, with how many times it occurred
with open(ROOT / "04_graph/triples.csv", "w", newline="", encoding="utf-8") as out:
    csv.writer(out).writerows([("subject", "relation", "object", "count"), *[(*e, c) for e, c in edges.items()]])

print(f"CLIENT: {setting('client') or '(not set)'}")
sys.path.insert(0, str(ROOT / "_system"))
from inbox import pending
_, waiting = pending()
print(f"Not extracted yet: {len(waiting)}" + ("  (run: python _system/inbox.py for the list)" if waiting else ""))
print(f"Waiting on review (not in database): {len(flagged)}")
for x in flagged: print(f"  - {x}")
print(f"Duplicates refused (already loaded): {len(dupes)}")
for x in dupes: print(f"  - {x}")
print(f"Matching exceptions: {len(X)}" + ("  (see 03_data/exceptions.md)" if X else ""))
for x in X: print(f"  - {x}")
print(f"Contract deadlines (next 90 days): {len(D)}")
for x in D: print(f"  - {x}")
print(f"Accruals to consider: {len(A)}" + (f"  (total {sum(a[4] or 0 for a in A):.2f})" if A else ""))
print(f"Rebuilt: {counts['invoice']} invoices, {counts['purchase_order']} purchase orders, "
      f"{counts['payment']} payments, {counts['contract']} contracts, {counts['receipt']} receipts, "
      f"{counts['bank']} bank lines, {len(edges)} unique edges")
