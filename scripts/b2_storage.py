"""Optional Backblaze B2 S3-compatible secondary media backend for Rolixa."""
import os
from pathlib import Path

PRESIGN_SECONDS = min(604800, int(os.environ.get("ROLIXA_B2_PRESIGN_SECONDS", "518400")))

def configured():
    return all(os.environ.get(k) for k in ("B2_ENDPOINT","B2_ACCESS_KEY_ID","B2_SECRET_ACCESS_KEY","B2_BUCKET"))

def _client():
    if not configured():
        raise RuntimeError("B2 is not configured.")
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["B2_ENDPOINT"].rstrip("/"),
        aws_access_key_id=os.environ["B2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["B2_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("B2_REGION", "us-west-004"),
    )

def upload_file(path, key, mime="application/octet-stream"):
    p=Path(path)
    client=_client()
    client.upload_file(str(p), os.environ["B2_BUCKET"], key, ExtraArgs={"ContentType":mime})
    url=client.generate_presigned_url("get_object", Params={"Bucket":os.environ["B2_BUCKET"],"Key":key}, ExpiresIn=PRESIGN_SECONDS)
    return {"bucket":os.environ["B2_BUCKET"],"key":key,"url":url,"bytes":p.stat().st_size,"backend":"b2"}

def download_file(key, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(os.environ["B2_BUCKET"], key, str(path))

def delete_keys(keys):
    client=_client()
    keys=[str(k) for k in keys if k]
    for i in range(0,len(keys),1000):
        client.delete_objects(Bucket=os.environ["B2_BUCKET"],Delete={"Objects":[{"Key":k} for k in keys[i:i+1000]],"Quiet":True})
    return len(keys)
