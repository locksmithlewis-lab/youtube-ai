"""Free-mode retention for the dedicated Rolixa Cloudflare R2 media bucket."""
import datetime as dt
import os

from r2_storage import configured, delete_keys, list_old_keys

days = max(1, int(os.environ.get("ROLIXA_R2_RETENTION_DAYS", "2")))
dry = os.environ.get("ROLIXA_R2_RETENTION_DRY_RUN", "0") == "1"
if not configured():
    print("R2 not configured; retention skipped.")
    raise SystemExit(0)
cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
candidates = list_old_keys(cutoff)
keys = [k for k, size, modified in candidates if k.lower().endswith(".mp4")]
if dry:
    print({"mode":"dry-run","days":days,"candidates":len(keys),"keys":keys[:20]})
else:
    deleted = delete_keys(keys)
    print({"mode":"delete","days":days,"candidates":len(keys),"deleted":deleted})
