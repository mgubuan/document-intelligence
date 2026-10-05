"""Run one SQL query: python q.py "SELECT * FROM invoices" """
import sqlite3, sys, pathlib
path = pathlib.Path(__file__).resolve().parent.parent / "03_data/invoices.db"
db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)  # read-only: no lock files
cur = db.execute(sys.argv[1])
print(" | ".join(d[0] for d in cur.description))
for row in cur:
    print(" | ".join(map(str, row)))
