"""Find invoices that don't have a record yet.
Run: python _system/inbox.py   -> lists every pending file (full path)
Reads the inbox setting from _shared/settings.md; searches subfolders too."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
INVOICE_TYPES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic"}

def inbox_root():
    for line in (ROOT / "_shared/settings.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("inbox_path:"):
            value = line.split(":", 1)[1].strip().strip('"')
            if value:
                p = pathlib.Path(value).expanduser()
                try:
                    ok = p.is_dir()
                except OSError:
                    ok = False
                if not ok:
                    raise SystemExit(f"inbox_path not found: {p}  (is the library synced and set to 'Always keep on this device'?)")
                return p
    return ROOT / "01_inbox"

def key(source_file):
    """source_file is stored relative to the inbox, with / separators."""
    s = source_file.replace("\\", "/").strip()
    return s[len("01_inbox/"):] if s.startswith("01_inbox/") else s

def recorded():
    keys = set()
    for f in (ROOT / "02_extracted").glob("*.md"):
        for line in f.read_text(encoding="utf-8").splitlines()[:20]:
            if line.startswith("source_file:"):
                keys.add(key(line.split(":", 1)[1]))
    return keys

def pending():
    root, done = inbox_root(), recorded()
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in INVOICE_TYPES
             and not any(part.startswith((".", "~")) for part in p.relative_to(root).parts)]
    return root, [p for p in sorted(files) if p.relative_to(root).as_posix() not in done]

if __name__ == "__main__":
    root, todo = pending()
    print(f"Inbox: {root}")
    print(f"Pending: {len(todo)}")
    for p in todo:
        print(f"  {p}   ->  source_file: {p.relative_to(root).as_posix()}")
