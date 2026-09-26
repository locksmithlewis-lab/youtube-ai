"""Two-day retention for the optional Rolixa Backblaze B2 media failover bucket."""
import datetime as dt
import os

from b2_storage import configured, delete_keys

days = max(1, int(os.environ.get("ROLIXA_B2_RETENTION_DAYS", "2")))
dry = os.environ.get("ROLIXA_B2_RETENTION_DRY_RUN", "0") == "1"

if not configured():
    print("B2 not configured; retention skipped.")
    raise SystemExit(0)

import b2_storage
client = b2_storage._client()
cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
paginator = client.get_paginator("list_objects_v2")
keys = []
for page in paginator.paginate(Bucket=os.environ["B2_BUCKET"]):
    for obj in page.get("Contents", []):
        modified = obj.get("LastModified")
        key = str(obj.get("Key") or "")
        if modified and modified < cutoff and key.lower().endswith(".mp4"):
            keys.append(key)

if dry:
    print({"mode": "dry-run", "days": days, "candidates": len(keys), "keys": keys[:20]})
else:
    deleted = delete_keys(keys)
    print({"mode": "delete", "days": days, "candidates": len(keys), "deleted": deleted})
