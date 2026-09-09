"""Reliable Supabase Storage transport for large video outputs.

Large files use the TUS resumable endpoint and the direct Storage hostname.
A narrowly-scoped compatibility shim upgrades legacy urllib POST uploads of
video/mp4 to the resumable path without touching unrelated HTTP traffic.
"""
import base64
import io
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TUS_VERSION = "1.0.0"
DEFAULT_CHUNK = 6 * 1024 * 1024
RESUMABLE_THRESHOLD = 6 * 1024 * 1024
VIDEO_BUCKET_SOFT_LIMIT = int(os.environ.get("ROLIXA_VIDEO_BUCKET_SOFT_LIMIT", str(96 * 1024 * 1024)))
_RAW_URLOPEN = urllib.request.urlopen


def _storage_base(supabase_url):
    parsed = urllib.parse.urlparse(str(supabase_url).rstrip("/"))
    host = parsed.netloc
    if host.endswith(".supabase.co") and ".storage.supabase.co" not in host:
        project_ref = host.split(".", 1)[0]
        host = f"{project_ref}.storage.supabase.co"
    return urllib.parse.urlunparse((parsed.scheme or "https", host, "", "", "", "")).rstrip("/")


def _auth_headers(key):
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _metadata(bucket, obj, mime):
    def b64(value):
        return base64.b64encode(str(value).encode()).decode()
    return ",".join([
        f"bucketName {b64(bucket)}",
        f"objectName {b64(obj)}",
        f"contentType {b64(mime)}",
        f"cacheControl {b64('3600')}",
    ])


def _http_error(exc):
    try:
        body = exc.read().decode("utf-8", "replace")[:1200]
    except Exception:
        body = ""
    return f"HTTP {getattr(exc, 'code', '?')} {getattr(exc, 'reason', '')}: {body}".strip()


def _open(req, timeout=120):
    try:
        return _RAW_URLOPEN(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_http_error(exc)) from exc


def _create_upload(supabase_url, key, bucket, obj, mime, size, upsert=True):
    endpoint = _storage_base(supabase_url) + "/storage/v1/upload/resumable"
    headers = {
        **_auth_headers(key),
        "Tus-Resumable": TUS_VERSION,
        "Upload-Length": str(size),
        "Upload-Metadata": _metadata(bucket, obj, mime),
        "x-upsert": "true" if upsert else "false",
        "Content-Length": "0",
    }
    req = urllib.request.Request(endpoint, data=b"", headers=headers, method="POST")
    with _open(req, timeout=120) as res:
        location = res.headers.get("Location")
    if not location:
        raise RuntimeError("Supabase TUS upload did not return a Location header.")
    return urllib.parse.urljoin(endpoint, location)


def _offset(upload_url, key):
    req = urllib.request.Request(
        upload_url,
        headers={**_auth_headers(key), "Tus-Resumable": TUS_VERSION},
        method="HEAD",
    )
    with _open(req, timeout=120) as res:
        return int(res.headers.get("Upload-Offset") or 0)


def _patch_chunk(upload_url, key, offset, chunk):
    headers = {
        **_auth_headers(key),
        "Tus-Resumable": TUS_VERSION,
        "Upload-Offset": str(offset),
        "Content-Type": "application/offset+octet-stream",
        "Content-Length": str(len(chunk)),
    }
    req = urllib.request.Request(upload_url, data=chunk, headers=headers, method="PATCH")
    with _open(req, timeout=180) as res:
        return int(res.headers.get("Upload-Offset") or (offset + len(chunk)))


def _verify_object(supabase_url, key, bucket, obj):
    url = str(supabase_url).rstrip("/") + f"/storage/v1/object/{urllib.parse.quote(bucket, safe='')}/{urllib.parse.quote(obj, safe='/')}"
    req = urllib.request.Request(
        url,
        headers={**_auth_headers(key), "Range": "bytes=0-0"},
        method="GET",
    )
    try:
        with _open(req, timeout=120) as res:
            res.read(1)
        return True
    except Exception:
        return False


def _tus_stream(stream, size, supabase_url, key, bucket, obj, mime, upsert=True, chunk_size=DEFAULT_CHUNK):
    last_error = None
    for create_attempt in range(3):
        try:
            upload_url = _create_upload(supabase_url, key, bucket, obj, mime, size, upsert)
            offset = 0
            stream.seek(0)
            while offset < size:
                stream.seek(offset)
                chunk = stream.read(min(chunk_size, size - offset))
                if not chunk:
                    raise RuntimeError(f"Unexpected EOF at {offset}/{size} bytes.")
                for patch_attempt in range(5):
                    try:
                        new_offset = _patch_chunk(upload_url, key, offset, chunk)
                        if new_offset <= offset:
                            raise RuntimeError(f"TUS upload offset did not advance from {offset}.")
                        offset = new_offset
                        break
                    except Exception as exc:
                        last_error = exc
                        if patch_attempt == 4:
                            raise
                        time.sleep(min(8, 1.5 * (patch_attempt + 1)))
                        try:
                            offset = _offset(upload_url, key)
                        except Exception:
                            pass
            final_offset = _offset(upload_url, key)
            if final_offset != size:
                raise RuntimeError(f"TUS upload incomplete: {final_offset}/{size} bytes.")
            if not _verify_object(supabase_url, key, bucket, obj):
                raise RuntimeError("Uploaded object could not be read back from Supabase Storage.")
            return {"bucket": bucket, "object": obj, "bytes": size, "transport": "tus"}
        except Exception as exc:
            last_error = exc
            if create_attempt < 2:
                time.sleep(2.0 * (create_attempt + 1))
    raise RuntimeError(f"Resumable Supabase upload failed after retries: {last_error}")


def _standard_bytes(data, supabase_url, key, bucket, obj, mime, upsert=True):
    url = str(supabase_url).rstrip("/") + f"/storage/v1/object/{urllib.parse.quote(bucket, safe='')}/{urllib.parse.quote(obj, safe='/')}"
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            **_auth_headers(key),
            "Content-Type": mime,
            "x-upsert": "true" if upsert else "false",
        },
        method="POST",
    )
    with _open(req, timeout=180) as res:
        res.read()
    if not _verify_object(supabase_url, key, bucket, obj):
        raise RuntimeError("Standard upload returned success but object read-back verification failed.")
    return {"bucket": bucket, "object": obj, "bytes": len(data), "transport": "standard"}


def _probe_duration(path):
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ]).decode().strip())


def _fit_video_bytes(data, limit=VIDEO_BUCKET_SOFT_LIMIT):
    if len(data) <= limit:
        return data
    with tempfile.TemporaryDirectory() as temp_dir:
        src = Path(temp_dir) / "source.mp4"
        dst = Path(temp_dir) / "fitted.mp4"
        src.write_bytes(data)
        duration = max(1.0, _probe_duration(src))
        total_kbps = max(520, int((limit * 8 * 0.93) / duration / 1000))
        audio_kbps = 128
        video_kbps = max(360, total_kbps - audio_kbps - 24)
        for attempt in range(4):
            vb = max(320, int(video_kbps * (0.88 ** attempt)))
            subprocess.run([
                "ffmpeg", "-y", "-i", str(src),
                "-map", "0:v:0", "-map", "0:a:0?",
                "-c:v", "libx264", "-preset", "veryfast",
                "-b:v", f"{vb}k", "-maxrate", f"{int(vb * 1.18)}k",
                "-bufsize", f"{int(vb * 2.0)}k",
                "-c:a", "aac", "-b:a", f"{audio_kbps}k",
                "-movflags", "+faststart", str(dst),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            fitted = dst.read_bytes()
            if len(fitted) <= limit:
                return fitted
        raise RuntimeError(
            f"Video is {len(data)} bytes and could not be compressed under the "
            f"{limit}-byte Storage safety limit without an unsafe quality reduction."
        )


def upload_bytes(data, supabase_url, key, bucket, obj, mime="application/octet-stream", upsert=True):
    if mime == "video/mp4" and bucket == "video-outputs":
        data = _fit_video_bytes(bytes(data))
    if len(data) <= RESUMABLE_THRESHOLD:
        return _standard_bytes(bytes(data), supabase_url, key, bucket, obj, mime, upsert)
    return _tus_stream(io.BytesIO(data), len(data), supabase_url, key, bucket, obj, mime, upsert)


def upload_file(path, supabase_url, key, bucket, obj, mime="application/octet-stream", upsert=True):
    path = Path(path)
    if mime == "video/mp4" and bucket == "video-outputs" and path.stat().st_size > VIDEO_BUCKET_SOFT_LIMIT:
        data = _fit_video_bytes(path.read_bytes())
        return upload_bytes(data, supabase_url, key, bucket, obj, mime, upsert)
    size = path.stat().st_size
    if size <= RESUMABLE_THRESHOLD:
        return _standard_bytes(path.read_bytes(), supabase_url, key, bucket, obj, mime, upsert)
    with path.open("rb") as stream:
        return _tus_stream(stream, size, supabase_url, key, bucket, obj, mime, upsert)


class _UploadResponse:
    def __init__(self, result):
        self.result = result
        self.headers = {}
        self.status = 200
    def read(self, *args, **kwargs):
        return json.dumps(self.result).encode()
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


def install_legacy_urllib_transport():
    """Upgrade only legacy large video-output POSTs to TUS."""
    original = urllib.request.urlopen
    if getattr(original, "_rolixa_storage_wrapped", False):
        return

    def wrapped(request, *args, **kwargs):
        try:
            if isinstance(request, urllib.request.Request):
                parsed = urllib.parse.urlparse(request.full_url)
                marker = "/storage/v1/object/"
                method = request.get_method().upper()
                content_type = request.headers.get("Content-type") or request.headers.get("Content-Type") or ""
                data = request.data
                if marker in parsed.path and method == "POST" and content_type.startswith("video/mp4") and data and len(data) > RESUMABLE_THRESHOLD:
                    tail = parsed.path.split(marker, 1)[1]
                    bucket_enc, obj_enc = tail.split("/", 1)
                    bucket = urllib.parse.unquote(bucket_enc)
                    obj = urllib.parse.unquote(obj_enc)
                    auth = request.headers.get("Authorization") or request.headers.get("authorization") or ""
                    key = auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else request.headers.get("apikey")
                    if key and bucket == "video-outputs":
                        supabase_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
                        result = upload_bytes(data, supabase_url, key, bucket, obj, "video/mp4", True)
                        return _UploadResponse(result)
        except Exception:
            raise
        return original(request, *args, **kwargs)

    wrapped._rolixa_storage_wrapped = True
    urllib.request.urlopen = wrapped
