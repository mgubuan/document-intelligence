# 01_inbox — where invoices come from

One job: hold the original invoices exactly as received.

- Default inbox: this folder. The user drops PDFs or images here.
- Or: `_shared/settings.md` → `inbox_path` points at an existing folder (e.g. a synced SharePoint library). Subfolders are searched too.
- Either way, NEVER edit, rename, move, or delete anything in the inbox — it is the client's filing system and the audit trail.
- A file is "done" when a record in `../02_extracted/` names it in `source_file` (path relative to the inbox).
- To see what's pending: `python _system/inbox.py`
