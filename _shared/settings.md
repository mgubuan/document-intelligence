# Settings

Whose books this workspace holds. Every document must be addressed to this client,
or it is held for review. Set it with: python _system/start.py --client "Name"

client: 

Where invoices come from. Leave blank to use the workspace's own `01_inbox/` folder.
To read a synced SharePoint/OneDrive library instead, paste its full path from File Explorer's address bar.
The workspace only ever READS this folder — it never moves, renames, or edits anything in it.

inbox_path:
