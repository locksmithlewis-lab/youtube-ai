"""Narrow retry transport for transient Supabase failures.

Retries idempotent HTTP methods. For visual_assets POSTs, a timeout is reconciled
by checking render_job_id + scene_index before retrying so a gateway timeout does
not either kill a render or create duplicate QC rows. Claim RPCs are never retried.
"""
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request

TRANSIENT={408,429,500,502,503,504}

class _Response:
    def __init__(self,payload=b''):
        self._payload=payload
        self.headers={}
        self.status=200
    def read(self,*args,**kwargs): return self._payload
    def __enter__(self): return self
    def __exit__(self,*args): return False


def _visual_asset_exists(opener, request, timeout):
    try:
        payload=json.loads((request.data or b'{}').decode())
        job=payload.get('render_job_id'); scene=payload.get('scene_index')
        if not job or scene is None:return False
        parsed=urllib.parse.urlparse(request.full_url)
        base=urllib.parse.urlunparse((parsed.scheme,parsed.netloc,'','','',''))
        query=urllib.parse.urlencode({
            'render_job_id':f'eq.{job}',
            'scene_index':f'eq.{scene}',
            'select':'id',
            'limit':'1',
        })
        headers={k:v for k,v in request.header_items() if k.lower() in ('apikey','authorization')}
        probe=urllib.request.Request(base+'/rest/v1/visual_assets?'+query,headers=headers,method='GET')
        with opener(probe,timeout=timeout) as res:
            rows=json.loads((res.read() or b'[]').decode())
        return bool(rows)
    except Exception:
        return False


def install():
    original=urllib.request.urlopen
    if getattr(original,'_rolixa_rest_retry_wrapped',False):return

    def wrapped(request,*args,**kwargs):
        if not isinstance(request,urllib.request.Request):
            return original(request,*args,**kwargs)
        parsed=urllib.parse.urlparse(request.full_url)
        if not parsed.netloc.endswith('supabase.co') and '.storage.supabase.co' not in parsed.netloc:
            return original(request,*args,**kwargs)
        method=request.get_method().upper()
        path=parsed.path
        retryable=method in ('GET','HEAD','PATCH','PUT','DELETE')
        visual_post=method=='POST' and path.endswith('/rest/v1/visual_assets')
        # Never replay non-idempotent RPC claims or arbitrary REST inserts.
        if not retryable and not visual_post:
            return original(request,*args,**kwargs)
        timeout=kwargs.get('timeout', args[0] if args else 90)
        attempts=4 if retryable else 3
        last=None
        for attempt in range(attempts):
            try:
                return original(request,*args,**kwargs)
            except urllib.error.HTTPError as exc:
                last=exc
                if exc.code not in TRANSIENT:raise
                if visual_post and _visual_asset_exists(original,request,timeout):
                    return _Response()
                if attempt==attempts-1:raise
                time.sleep(min(6.0,0.8*(2**attempt)))
            except (TimeoutError,urllib.error.URLError) as exc:
                last=exc
                if visual_post and _visual_asset_exists(original,request,timeout):
                    return _Response()
                if attempt==attempts-1:raise
                time.sleep(min(6.0,0.8*(2**attempt)))
        raise last

    wrapped._rolixa_rest_retry_wrapped=True
    urllib.request.urlopen=wrapped
