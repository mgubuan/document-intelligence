"""STEP 1 of every session. Shows which client's books these are, what state they're in,
and the ONE thing to do next.

    python _system/start.py                          -> status + next step
    python _system/start.py --client "Riverside Dental"   -> name the client (first-time setup;
                                                        only with the name the user confirmed)
"""
import pathlib, re, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "_shared/settings.md"
sys.path.insert(0, str(ROOT / "_system"))

def setting(key):
    for line in SETTINGS.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""

def set_client(name):
    s = SETTINGS.read_text(encoding="utf-8")
    s = re.sub(r"(?m)^client:.*$", f"client: {name}", s) if re.search(r"(?m)^client:", s) else f"client: {name}\n" + s
    SETTINGS.write_text(s, encoding="utf-8")

def table_rows(name):
    p = ROOT / "_shared" / name
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("|")][2:] if p.exists() else []  # skip header + divider

def front(f):
    parts = f.read_text(encoding="utf-8").split("---", 2)
    return dict((k.strip(), v.strip()) for k, v in (l.split(":", 1) for l in parts[1].splitlines() if ":" in l)) if len(parts) == 3 else {}

if "--client" in sys.argv:
    name = sys.argv[sys.argv.index("--client") + 1].strip()
    set_client(name)
    print(f"Client set to: {name}\n")

client = setting("client")
print("=" * 60)
print(f"CLIENT: {client or '(not set)'}")
print("=" * 60)

# ---- 1. setup
vendors, accounts = table_rows("vendors.md"), table_rows("chart-of-accounts.md")
try:
    from inbox import pending, inbox_root
    root, waiting = pending()
    inbox_ok, inbox_msg = True, str(root)
except SystemExit as e:
    inbox_ok, inbox_msg, waiting = False, str(e), []
print("\nSetup")
print(f"  {'OK ' if client else 'MISSING'} client name ................ {client or 'not set'}")
print(f"  {'OK ' if vendors else 'MISSING'} vendor list ................ {len(vendors)} vendors")
print(f"  {'OK ' if accounts else 'MISSING'} chart of accounts .......... {len(accounts)} accounts")
print(f"  {'OK ' if inbox_ok else 'MISSING'} inbox ...................... {inbox_msg}")

# ---- 2. state
recs = [f for f in (ROOT / "02_extracted").glob("*.md") if f.name != "CONTEXT.md" and not f.name.startswith("_")]
metas = [(f, front(f)) for f in recs]
unstandardized = [f.name for f, m in metas if "vendor" not in m]
flagged = [(f.name, m.get("review_reason", "")) for f, m in metas if m.get("needs_review") == "true"]
db = ROOT / "03_data/invoices.db"
newest = max((f.stat().st_mtime for f in recs), default=0)
stale = recs and (not db.exists() or db.stat().st_mtime < newest)
exceptions = 0
if db.exists():
    try: exceptions = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True).execute("SELECT COUNT(*) FROM exceptions").fetchone()[0]
    except sqlite3.Error: pass
print("\nState")
print(f"  new documents in inbox ...... {len(waiting)}")
print(f"  records not yet standardized  {len(unstandardized)}")
print(f"  flagged, waiting on a person  {len(flagged)}")
print(f"  database up to date ......... {'no' if stale else 'yes'}")
print(f"  matching exceptions ......... {exceptions}")

# ---- 3. the one next step
print("\nNEXT STEP")
if not client:
    print("  Ask the user: \"Which client's books are these?\" Then run:\n"
          "    python _system/start.py --client \"<name they confirm>\"")
elif not vendors or not accounts:
    print("  Ask the user to fill in _shared/vendors.md and _shared/chart-of-accounts.md for this client.\n"
          "  Don't invent them. Then run start.py again.")
elif not inbox_ok:
    print(f"  Fix the inbox: {inbox_msg}\n  Ask the user to sync the folder or correct inbox_path in _shared/settings.md.")
elif waiting:
    print(f"  Extract {len(waiting)} new document(s). Follow 02_extracted/CONTEXT.md, one record per file:")
    for p in waiting[:20]: print(f"    - {p.relative_to(root).as_posix()}")
    if len(waiting) > 20: print(f"    ... and {len(waiting) - 20} more (python _system/inbox.py for all)")
    print("  Then run: python _system/standardize.py && python _system/rebuild.py && python _system/start.py")
elif unstandardized:
    print("  Run: python _system/standardize.py && python _system/rebuild.py && python _system/start.py")
elif stale:
    print("  Run: python _system/rebuild.py && python _system/start.py")
elif flagged:
    print("  Show the user what's flagged and why, and for each one suggest the fix: an alias or keyword")
    print("  to add to an EXISTING vendor or account in _shared/ (see 02_extracted/CONTEXT.md). They decide;")
    print("  you never edit _shared/ or clear flags yourself:")
    for n, r in flagged[:20]: print(f"    - {n}: {r}")
    print("  After they fix a master list or add approved_by_human: true, run:\n"
          "    python _system/standardize.py && python _system/rebuild.py && python _system/start.py")
else:
    print(f"  Ready. Ask the user what they'd like to know about {client}'s books.")
    if exceptions: print(f"  Mention first: {exceptions} matching exception(s) in 03_data/exceptions.md.")
