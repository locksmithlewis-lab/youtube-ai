"""Cloudflare R2 object-storage backend for Rolixa.

R2 is used only for large media when R2 credentials are configured. Supabase
remains the system-of-record database and fallback media store.
"""
import os
from pathlib import Path

FREE_STORAGE_GB = float(os.environ.get("ROLIXA_R2_FREE_STORAGE_GB", "10"))
MAX_STORAGE_BYTES = int(os.environ.get(
    "ROLIXA_R2_MAX_STORAGE_BYTES",
    str(int(FREE_STORAGE_GB * 1_000_000_000 * 0.95)),
))
PRESIGN_SECONDS = min(604800, int(os.environ.get("ROLIXA_R2_PRESIGN_SECONDS", "518400")))


def configured():
    return all(os.environ.get(k) for k in (
        "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"
    ))


def _client():
    if not configured():
        raise RuntimeError(
            "R2 is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY and R2_BUCKET."
        )
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for Cloudflare R2 storage.") from exc
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def usage_bytes():
    total = 0
    token = None
    client = _client()
    while True:
        args = {"Bucket": os.environ["R2_BUCKET"], "MaxKeys": 1000}
        if token:
            args["ContinuationToken"] = token
        page = client.list_objects_v2(**args)
        total += sum(int(x.get("Size") or 0) for x in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return total
        token = page.get("NextContinuationToken")
        if not token:
            return total


def _guard_capacity(additional_bytes):
    current = usage_bytes()
    projected = current + int(additional_bytes)
    if projected > MAX_STORAGE_BYTES:
        raise RuntimeError(
            f"R2 free-mode storage guard blocked upload: current={current} "
            f"bytes, additional={additional_bytes}, projected={projected}, "
            f"limit={MAX_STORAGE_BYTES}. Delete expired media first."
        )
    return current


def upload_file(path, key, mime="application/octet-stream", upsert=True):
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"R2 upload source is missing or empty: {path}")
    _guard_capacity(path.stat().st_size)
    client = _client()
    extra = {"ContentType": mime, "CacheControl": "public, max-age=3600"}
    if upsert:
        client.upload_file(str(path), os.environ["R2_BUCKET"], key, ExtraArgs=extra)
    else:
        client.put_object(Bucket=os.environ["R2_BUCKET"], Key=key, Body=path.open("rb"), **extra)
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET"], "Key": key},
        ExpiresIn=PRESIGN_SECONDS,
    )
    return {"bucket": os.environ["R2_BUCKET"], "key": key, "url": url, "bytes": path.stat().st_size}


def download_file(key, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(os.environ["R2_BUCKET"], key, str(path))


def delete_keys(keys):
    keys = [str(k) for k in keys if k]
    if not keys:
        return 0
    client = _client()
    deleted = 0
    for i in range(0, len(keys), 1000):
        batch = keys[i:i + 1000]
        client.delete_objects(
            Bucket=os.environ["R2_BUCKET"],
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
        deleted += len(batch)
    return deleted


def list_old_keys(cutoff):
    """Return (key, size, last_modified) for objects older than cutoff."""
    client = _client()
    out = []
    token = None
    while True:
        args = {"Bucket": os.environ["R2_BUCKET"], "MaxKeys": 1000}
        if token:
            args["ContinuationToken"] = token
        page = client.list_objects_v2(**args)
        for item in page.get("Contents", []):
            if item.get("LastModified") and item["LastModified"] < cutoff:
                out.append((item["Key"], int(item.get("Size") or 0), item["LastModified"]))
        if not page.get("IsTruncated"):
            return out
        token = page.get("NextContinuationToken")
        if not token:
            return out
