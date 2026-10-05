"""Standardize records against the master lists in _shared/.
Handles three record types (set by `record_type:` in each record; missing = invoice):
  invoice         -> clean vendor, doc_type, GL code per line, line items must sum to total
  purchase_order  -> clean vendor, GL code per line, line items must sum to total
  payment         -> clean vendor, applied amounts must sum to the payment amount
  contract        -> clean vendor, date/renewal sanity checks, and ALWAYS held for a person to confirm
                     the key terms against the signed contract (cleared only by approved_by_human: true)
Uses Jev if JEV_API_KEY is set, otherwise an offline matcher. Raw values are never overwritten.
Run: python _system/standardize.py         -> new records + anything still flagged
     python _system/standardize.py --all   -> also re-code settled records (changes history)
Records with approved_by_human: true are never changed."""
import difflib, json, os, pathlib, re, sys, urllib.request

REDO_ALL = "--all" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent.parent
THRESHOLD = 0.80  # below this confidence -> needs_review

# id field, total field, does it have GL-coded lines?, which table column holds the amount
TYPES = {
    "invoice":        {"id": "invoice_no", "total": "total",  "gl": True,  "cols": 4, "amt": 3},
    "purchase_order": {"id": "po_no",      "total": "total",  "gl": True,  "cols": 4, "amt": 3},
    "payment":        {"id": "payment_id", "total": "amount", "gl": False, "cols": 2, "amt": 1},
    "contract":       {"id": "contract_id"},
}

import datetime
def parse_date(x):
    try: return datetime.date.fromisoformat(str(x).strip()[:10])
    except ValueError: return None

def contract_issues(meta):
    """Sanity checks. Contracts are always held for human confirmation on top of these."""
    out = []
    eff, end = parse_date(meta.get("effective_date")), parse_date(meta.get("end_date"))
    if not eff: out.append("effective_date missing or unreadable")
    if (meta.get("end_date") or "").strip() and not end: out.append("end_date unreadable")
    if eff and end and end < eff: out.append("end_date is before effective_date")
    ar = (meta.get("auto_renew") or "").strip().lower()
    if ar not in ("yes", "no"): out.append("auto_renew unknown - check the renewal clause")
    if ar == "yes" and not (meta.get("notice_days") or "").strip().isdigit():
        out.append("auto-renews but notice_days is missing")
    return out

def table(name):
    rows = [[c.strip() for c in l.strip().strip("|").split("|")]
            for l in (ROOT / "_shared" / name).read_text(encoding="utf-8").splitlines() if l.startswith("|")]
    return {r[0]: [k.strip().lower() for k in r[1].split(";") if k.strip()] for r in rows[2:]}

VENDORS, ACCOUNTS, DOCTYPES = table("vendors.md"), table("chart-of-accounts.md"), table("doc-types.md")

# Whose books are these? Every document must be addressed to this client, or it's held for review.
CLIENT = next((l.split(":", 1)[1].strip() for l in (ROOT / "_shared/settings.md").read_text(encoding="utf-8").splitlines()
               if l.startswith("client:")), "")
if not CLIENT:
    raise SystemExit('No client set for this workspace. Run: python _system/start.py --client "<client name>"')
norm = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower())

def wrong_client(meta):
    c = meta.get("client", "")
    return [] if norm(c) == norm(CLIENT) else [f"addressed to '{c or 'no client'}', but this workspace is {CLIENT}"]

# ---------- Jev (hosted, fast). Check request shape against Jev's docs before relying on it. ----------
def jev(text, options):
    req = urllib.request.Request(
        "https://jevtypesafeai.com/api/v1/decide",
        data=json.dumps({"input": text, "questions": {"q": {"options": list(options)}}}).encode(),
        headers={"Authorization": f"Bearer {os.environ['JEV_API_KEY']}", "Content-Type": "application/json"})
    out = json.load(urllib.request.urlopen(req, timeout=10))["answers"]["q"]
    return out["key"], float(out["confidence"])

# ---------- Offline fallback (no network, no AI) ----------
def offline(text, options):
    t = text.lower()
    best, score = None, 0.0
    for opt, keys in options.items():
        for k in [opt.lower(), *keys]:
            s = 1.0 if k == t else 0.95 if k and k in t else difflib.SequenceMatcher(None, k, t).ratio()
            if s > score:
                best, score = opt, s
    return best, round(score, 2)

def offline_doctype(text):
    t = "\n".join(l for l in text.lower().splitlines() if not l.startswith("#"))  # ignore template heading
    hits = {d: sum(k in t for k in keys) for d, keys in DOCTYPES.items()}
    best = max(hits, key=hits.get)
    return (best, 0.9) if hits[best] else ("invoice", 0.5)

def classify(text, options):
    if os.environ.get("JEV_API_KEY"):
        try:
            return jev(text, options)
        except Exception as e:
            print(f"  Jev failed ({e}); using offline matcher")
    return offline_doctype(text) if options is DOCTYPES else offline(text, options)

skipped = 0
for f in sorted((ROOT / "02_extracted").glob("*.md")):
    if f.name.startswith("_") or f.name == "CONTEXT.md":
        continue
    _, front, body = f.read_text(encoding="utf-8").split("---", 2)
    meta = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in front.strip().splitlines() if ":" in l)}
    rtype = meta.get("record_type", "invoice")
    if rtype not in TYPES:
        print(f"{f.name}: unknown record_type '{rtype}' - skipped"); continue
    T = TYPES[rtype]
    approved = meta.get("approved_by_human") == "true"
    settled = "vendor" in meta and meta.get("needs_review") == "false"
    # settled records are left alone; approved settled records are left alone even with --all.
    # an approved record that is still flagged IS processed, so the approval clears the flag.
    if settled and (approved or not REDO_ALL):
        skipped += 1
        continue  # protect history: settled records don't silently change

    vendor, v_conf = classify(meta["vendor_raw"], VENDORS)
    if rtype == "contract":
        issues = contract_issues(meta) + wrong_client(meta)
        if v_conf < THRESHOLD:
            vendor = "UNMATCHED"; issues.append("low-confidence vendor match")
        issues.append("confirm key terms against the signed contract")
        if approved: issues = []
        body = "\n".join(l.replace(f"[[{meta['vendor_raw']}]]", f"[[{vendor}]]") for l in body.splitlines())
        meta.update(record_type=rtype, vendor=vendor, doc_type="contract", confidence=v_conf,
                    needs_review=str(bool(issues)).lower(), review_reason="; ".join(issues) or "none")
        f.write_text("---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---" + body + "\n", encoding="utf-8")
        print(f"{rtype:15} {meta['contract_id']}: '{meta['vendor_raw']}' -> {vendor}" + (f"  <-- REVIEW: {'; '.join(issues)}" if issues else ""))
        continue
    doc, d_conf = classify(body, DOCTYPES) if rtype == "invoice" else (rtype, 1.0)
    confs, lines, n, item_sum = [v_conf, d_conf], [], 0, 0.0
    for l in body.splitlines():
        if l.startswith("|"):
            cells = [c.strip() for c in l.strip().strip("|").split("|")][:T["cols"]]
            if n >= 2:  # data rows
                try: item_sum += float(cells[T["amt"]])
                except (ValueError, IndexError): pass
            if T["gl"]:
                if n == 0: cells.append("gl_account")
                elif n == 1: cells.append("---")
                else:
                    gl, g_conf = classify(cells[0], ACCOUNTS)
                    if g_conf < THRESHOLD: gl = "9999 Uncategorized"
                    cells.append(gl); confs.append(g_conf)
            n += 1
            l = "| " + " | ".join(cells) + " |"
        lines.append(l)

    if v_conf < THRESHOLD:
        vendor = "UNMATCHED"
    issues = []
    try:
        if abs(item_sum - float(meta[T["total"]])) > 0.01:
            what = "applied amounts" if rtype == "payment" else "line items"
            issues.append(f"{what} sum to {item_sum:.2f}, {T['total']} says {meta[T['total']]}")
    except (ValueError, KeyError):
        issues.append(f"{T['total']} unreadable")
    if min(confs) < THRESHOLD:
        issues.append("low-confidence match")
    issues += wrong_client(meta)
    lines = [l.replace(f"[[{meta['vendor_raw']}]]", f"[[{vendor}]]") if "[[" in l else l for l in lines]
    if approved:
        issues = []
    meta.update(record_type=rtype, vendor=vendor, doc_type=doc, confidence=min(confs),
                needs_review=str(bool(issues)).lower(), review_reason="; ".join(issues) or "none")
    f.write_text("---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---" + "\n".join(lines) + "\n", encoding="utf-8")
    flag = f"  <-- REVIEW: {'; '.join(issues)}" if issues else ""
    print(f"{rtype:15} {meta.get(T['id'], f.name)}: '{meta['vendor_raw']}' -> {vendor} | conf {min(confs)}{flag}")

print(f"Left unchanged (already settled): {skipped}" + ("" if REDO_ALL else "  - use --all to re-code history"))
