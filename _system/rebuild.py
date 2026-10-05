"""Rebuild the database, graph, and exceptions report from the markdown records. Safe to run anytime.
Only approved records (needs_review: false) are loaded; flagged ones are listed in the review_queue table.
"Today" for aging and deadlines is the real date, or INTEL_AS_OF=YYYY-MM-DD if set (used by the self-test)."""
import csv, datetime, os, pathlib, shutil, sqlite3, sys, tempfile
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "03_data/invoices.db"
TOL = 0.01
AS_OF = datetime.date.fromisoformat(os.environ.get("INTEL_AS_OF") or datetime.date.today().isoformat())

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

def parse_date(x):
    try: return datetime.date.fromisoformat(str(x).strip()[:10])
    except ValueError: return None

num = lambda x: float(x) if str(x).strip() not in ("", "UNKNOWN") else None

# build in a temp file, then copy into place: atomic, and works on synced/network folders
TMP = pathlib.Path(tempfile.mkdtemp()) / "invoices.db"
db = sqlite3.connect(TMP)
db.execute("PRAGMA foreign_keys = ON")
db.executescript("""
-- Documents are unique per vendor + number (two vendors can both use "1001").
CREATE TABLE invoices(invoice_no TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, doc_type, client, date, due_date,
    total REAL NOT NULL, currency, po_no, file, PRIMARY KEY (vendor, invoice_no));
CREATE TABLE line_items(vendor TEXT NOT NULL, invoice_no TEXT NOT NULL, description, qty REAL, unit_price REAL, amount REAL, gl_account,
    FOREIGN KEY (vendor, invoice_no) REFERENCES invoices(vendor, invoice_no));
CREATE TABLE purchase_orders(po_no TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, client, date,
    total REAL NOT NULL, currency, file, PRIMARY KEY (vendor, po_no));
CREATE TABLE po_lines(vendor TEXT NOT NULL, po_no TEXT NOT NULL, description, qty REAL, unit_price REAL, amount REAL, gl_account,
    FOREIGN KEY (vendor, po_no) REFERENCES purchase_orders(vendor, po_no));
CREATE TABLE payments(payment_id TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, client, date,
    amount REAL NOT NULL, method, currency, file, PRIMARY KEY (vendor, payment_id));
-- One payment can cover several invoices. Applications point at invoices by vendor + number;
-- they are checked in the exceptions report instead of a hard key, because the invoice may still be in review.
CREATE TABLE payment_applications(vendor TEXT NOT NULL, payment_id TEXT NOT NULL, invoice_no TEXT NOT NULL, amount REAL NOT NULL,
    FOREIGN KEY (vendor, payment_id) REFERENCES payments(vendor, payment_id));
CREATE TABLE contracts(contract_id TEXT NOT NULL, vendor TEXT NOT NULL, vendor_raw, client, title, contract_type,
    effective_date, end_date, auto_renew, renewal_term, notice_days INTEGER, notice_deadline, payment_terms,
    billing_frequency, recurring_amount REAL, total_value REAL, currency, file, PRIMARY KEY (vendor, contract_id));
CREATE TABLE contract_terms(vendor TEXT NOT NULL, contract_id TEXT NOT NULL, term, value, section,
    FOREIGN KEY (vendor, contract_id) REFERENCES contracts(vendor, contract_id));
CREATE TABLE contract_rates(vendor TEXT NOT NULL, contract_id TEXT NOT NULL, description, unit_price REAL, unit,
    FOREIGN KEY (vendor, contract_id) REFERENCES contracts(vendor, contract_id));
-- Housekeeping tables, so status questions can be answered with SQL too.
CREATE TABLE settings(as_of TEXT);
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
         CAST(julianday((SELECT as_of FROM settings)) - julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) AS INTEGER) AS days_past_due,
         CASE WHEN julianday((SELECT as_of FROM settings)) <= julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) THEN 'current'
              WHEN julianday((SELECT as_of FROM settings)) - julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) <= 30 THEN '1-30'
              WHEN julianday((SELECT as_of FROM settings)) - julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) <= 60 THEN '31-60'
              WHEN julianday((SELECT as_of FROM settings)) - julianday(COALESCE(NULLIF(i.due_date, ''), i.date)) <= 90 THEN '61-90'
              ELSE '90+' END AS bucket
  FROM invoice_balances b JOIN invoices i ON i.vendor = b.vendor AND i.invoice_no = b.invoice_no
  WHERE b.status IN ('open', 'partial') AND b.open_balance > 0;   -- credits are in invoice_balances, not aging
-- PO consumption: ordered vs billed vs remaining.
CREATE VIEW po_status AS
  SELECT p.vendor, p.po_no, p.date, p.total AS ordered, ROUND(COALESCE(SUM(i.total), 0), 2) AS billed,
         ROUND(p.total - COALESCE(SUM(i.total), 0), 2) AS remaining, COUNT(i.invoice_no) AS invoices,
         CASE WHEN COALESCE(SUM(i.total), 0) = 0 THEN 'open'
              WHEN p.total - SUM(i.total) > 0.01 THEN 'partly billed'
              WHEN p.total - SUM(i.total) < -0.01 THEN 'over-billed' ELSE 'fully billed' END AS status
  FROM purchase_orders p LEFT JOIN invoices i ON i.vendor = p.vendor AND i.po_no = p.po_no
  GROUP BY p.vendor, p.po_no;
""")
db.execute("INSERT INTO settings VALUES (?)", (AS_OF.isoformat(),))

triples, flagged, dupes, loaded = [], [], [], {}
counts = Counter()
# shortest name first, so the original "INV-1001.md" wins over "INV-1001-copy.md" when duplicates arrive
for f in sorted((ROOT / "02_extracted").glob("*.md"), key=lambda p: (len(p.name), p.name)):
    if f.name.startswith("_") or f.name == "CONTEXT.md":
        continue
    m, rows = parse(f)
    rtype = m.get("record_type", "invoice")
    if "vendor" not in m:
        raise SystemExit(f"{f.name} isn't standardized yet - run: python _system/standardize.py")
    rid = m.get({"invoice": "invoice_no", "purchase_order": "po_no", "payment": "payment_id", "contract": "contract_id"}[rtype])
    if m.get("needs_review") == "true":
        flagged.append(f"{rtype} {rid} ({m.get('review_reason', '')})")
        db.execute("INSERT INTO review_queue VALUES (?,?,?,?,?)", (rtype, rid, m.get("vendor_raw"), m.get("review_reason"), f.name))
        continue
    v, key = m["vendor"], (rtype, m["vendor"], rid)
    node = f"{v}/{rid}"  # graph node name matches the database key
    try:
        if rtype == "invoice":
            db.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?,?)", (rid, v, m["vendor_raw"], m.get("doc_type"), m.get("client"),
                       m.get("date"), m.get("due_date"), m["total"], m.get("currency"), m.get("po_no") or None, f.name))
            rows = [r for r in rows if len(r) == 5]
            db.executemany("INSERT INTO line_items VALUES (?,?,?,?,?,?,?)", [(v, rid, *r) for r in rows])
            triples += [(v, "billed", m["client"]), (v, "issued", node), (node, "billed_to", m["client"]),
                        (node, "dated", m["date"][:7]), (node, "is_a", m.get("doc_type"))]
            triples += [(node, "includes", r[0]) for r in rows] + [(r[0], "coded_to", r[4]) for r in rows]
            if m.get("po_no"): triples.append((node, "bills_against", f"{v}/{m['po_no']}"))
        elif rtype == "purchase_order":
            db.execute("INSERT INTO purchase_orders VALUES (?,?,?,?,?,?,?,?)", (rid, v, m["vendor_raw"], m.get("client"),
                       m.get("date"), m["total"], m.get("currency"), f.name))
            rows = [r for r in rows if len(r) == 5]
            db.executemany("INSERT INTO po_lines VALUES (?,?,?,?,?,?,?)", [(v, rid, *r) for r in rows])
            triples += [(m["client"], "ordered_from", v), (node, "ordered_by", m["client"]), (node, "ordered_from", v),
                        (node, "dated", m["date"][:7])]
            triples += [(node, "includes", r[0]) for r in rows] + [(r[0], "coded_to", r[4]) for r in rows]
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
            db.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?)", (rid, v, m["vendor_raw"], m.get("client"),
                       m.get("date"), m["amount"], m.get("method"), m.get("currency"), f.name))
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
    counts[rtype] += 1

# ---------- matching checks: reported, never blocking ----------
X = []
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
for v, inv, desc, billed, agreed, ctr in db.execute(f"""SELECT i.vendor, i.invoice_no, l.description, l.unit_price, r.unit_price, c.contract_id
        FROM invoices i JOIN line_items l ON l.vendor = i.vendor AND l.invoice_no = i.invoice_no
        JOIN contracts c ON c.vendor = i.vendor AND {IN_TERM}
        JOIN contract_rates r ON r.vendor = c.vendor AND r.contract_id = c.contract_id AND LOWER(r.description) = LOWER(l.description)
        WHERE l.unit_price > r.unit_price + ?""", (TOL,)):
    X.append(f"Above contract rate: {v} {inv} bills '{desc}' at {billed:.2f}; contract {ctr} says {agreed:.2f}.")
for v, ctr, cap, spent in db.execute(f"""SELECT c.vendor, c.contract_id, c.total_value, ROUND(SUM(i.total), 2)
        FROM contracts c JOIN invoices i ON i.vendor = c.vendor AND {IN_TERM}
        WHERE c.total_value IS NOT NULL GROUP BY c.vendor, c.contract_id HAVING SUM(i.total) > c.total_value + ?""", (TOL,)):
    X.append(f"Over contract value: {v} {ctr} is capped at {cap:.2f}; invoices in its term total {spent:.2f}.")
for inv_v, inv, ctr in db.execute(f"""SELECT i.vendor, i.invoice_no, c.contract_id FROM invoices i
        JOIN contracts c ON c.vendor = i.vendor AND {IN_TERM}"""):
    triples.append((f"{inv_v}/{inv}", "under_contract", f"{inv_v}/{ctr}"))

# deadlines: notice dates coming up in the next 90 days (or missed, before the contract ends)
today = AS_OF
D = []
for v, ctr, title, end, deadline, ar, term in db.execute("""SELECT vendor, contract_id, title, end_date, notice_deadline,
        auto_renew, renewal_term FROM contracts WHERE notice_deadline IS NOT NULL ORDER BY notice_deadline"""):
    dl, en = datetime.date.fromisoformat(deadline), datetime.date.fromisoformat(end)
    days = (dl - today).days
    what = f"it auto-renews for {term}" if ar == "yes" else "it ends"
    status = "upcoming" if 0 <= days <= 90 else "missed" if days < 0 <= (en - today).days else "later" if days > 90 else "ended"
    db.execute("INSERT INTO deadlines VALUES (?,?,?,?,?,?,?)", (v, ctr, title, deadline, days, end, status))
    if status == "upcoming":
        D.append(f"{deadline} ({days} days): last day to give notice on {v} {ctr} ({title}), or {what} on {end}.")
    elif status == "missed":
        D.append(f"MISSED {deadline}: notice window for {v} {ctr} closed; {what} on {end}.")
KINDS = {"Over-billed", "Overpaid", "Outside contract", "Above contract rate", "Over contract value"}
db.executemany("INSERT INTO exceptions VALUES (?,?)", [(x.split(":")[0] if x.split(":")[0] in KINDS else "Missing link", x) for x in X])

db.commit()
db.close()
shutil.copyfile(TMP, DB)

(ROOT / "03_data/exceptions.md").write_text(
    "# Exceptions\n\nGenerated by rebuild.py - do not edit. Fix the records, then rebuild.\n\n"
    + ("\n".join(f"- {x}" for x in X) if X else "None. Everything matches.")
    + "\n\n## Contract deadlines (next 90 days)\n\n" + ("\n".join(f"- {x}" for x in D) if D else "None.") + "\n", encoding="utf-8")

edges = Counter(triples)  # each edge once, with how many times it occurred
with open(ROOT / "04_graph/triples.csv", "w", newline="", encoding="utf-8") as out:
    csv.writer(out).writerows([("subject", "relation", "object", "count"), *[(*e, c) for e, c in edges.items()]])

client = next((l.split(":", 1)[1].strip() for l in (ROOT / "_shared/settings.md").read_text(encoding="utf-8").splitlines()
               if l.startswith("client:")), "") or "(not set)"
print(f"CLIENT: {client}")
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
print(f"Rebuilt: {counts['invoice']} invoices, {counts['purchase_order']} purchase orders, "
      f"{counts['payment']} payments, {counts['contract']} contracts, {len(edges)} unique edges")
