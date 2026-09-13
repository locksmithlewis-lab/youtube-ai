import json
import re
import urllib.parse
import urllib.request

USER_AGENT='CreatorPipeline/1.0 (source-backed short-form writer)'
GENERIC_MARKERS=(
    'the important part is the connection between',
    'now flip the perspective',
    'the takeaway is simple',
    'start with the obvious version',
    'here is the key fact about',
)


def _words(text):
    return re.findall(r"[A-Za-z0-9']+",str(text or ''))


def needs_script(project):
    fmt=str(project.get('format') or '').lower()
    target=int(project.get('target_duration_seconds') or 60)
    if fmt not in ('short','shorts','story') or target>120:
        return False
    script=str(project.get('script') or '').strip()
    hook=str(project.get('hook') or '').strip()
    low=script.lower()
    weak_hook=(len(_words(hook))<5 or len(_words(hook))>18 or not re.search(r'(?i)(\?|\bwhy\b|\bhow\b|\bbut\b|\bproblem\b|\bcost\b|\bpaid\b|\bsuddenly\b|\bhidden\b|\bchanged\b)',hook))
    return len(_words(script))<55 or any(marker in low for marker in GENERIC_MARKERS) or weak_hook


def _source(topic):
    params=urllib.parse.urlencode({
        'action':'query','generator':'search','gsrsearch':topic,'gsrlimit':'1',
        'prop':'extracts|info','exintro':'1','explaintext':'1','inprop':'url',
        'format':'json','formatversion':'2'
    })
    req=urllib.request.Request('https://en.wikipedia.org/w/api.php?'+params,headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=20) as response:
        data=json.loads(response.read().decode())
    pages=((data.get('query') or {}).get('pages') or [])
    if not pages:
        raise RuntimeError('No reliable public reference found for this Short topic.')
    page=pages[0]
    extract=re.sub(r'\s+',' ',str(page.get('extract') or '')).strip()
    if len(_words(extract))<45:
        raise RuntimeError('Public reference is too thin to support a publishable factual Short.')
    return {'title':str(page.get('title') or topic),'url':str(page.get('fullurl') or ''),'extract':extract}


def _sentences(text):
    return [re.sub(r'\s+',' ',s).strip() for s in re.split(r'(?<=[.!?])\s+',text) if len(_words(s))>=6]


def _compact_claim(sentence,index):
    s=re.sub(r'\[[^\]]+\]','',sentence).strip()
    s=re.sub(r'\([^)]{20,}\)','',s).strip()
    max_words=18 if index<2 else 21
    ws=s.split()
    if len(ws)>max_words:
        s=' '.join(ws[:max_words]).rstrip(',;:')+'.'
    if not s.endswith(('.', '!', '?')):
        s+='.'
    if index==0:
        return s
    prefixes=('But ','Then ','That matters because ','The bigger consequence is ')
    lower=s[0].lower()+s[1:] if len(s)>1 else s.lower()
    return prefixes[(index-1)%len(prefixes)]+lower


def _make_hook(project,topic):
    current=re.sub(r'\s+',' ',str(project.get('hook') or '')).strip()
    if 5<=len(_words(current))<=18 and re.search(r'(?i)(\?|\bwhy\b|\bhow\b|\bbut\b|\bproblem\b|\bcost\b|\bpaid\b|\bsuddenly\b|\bhidden\b|\bchanged\b)',current):
        return current
    return f'Why does {topic} matter more than the headline makes it seem?'


def write(project):
    topic=str(project.get('topic') or project.get('title') or '').strip()
    if len(_words(topic))<2:
        raise RuntimeError('Short topic is too vague to source and write automatically.')
    source=_source(topic)
    source_sentences=_sentences(source['extract'])
    hook=_make_hook(project,topic)
    claims=[]
    total=len(_words(hook))
    for sentence in source_sentences[:10]:
        claim=_compact_claim(sentence,len(claims))
        n=len(_words(claim))
        if claims and total+n>118:
            break
        claims.append(claim);total+=n
        if total>=82 and len(claims)>=4:
            break
    if len(claims)<4 or total<65:
        raise RuntimeError('Source could not support enough distinct narration beats for a publishable Short.')
    closing=f'That is the part of {topic} the headline alone does not explain.'
    script=' '.join([hook]+claims+[closing])
    if len(_words(script))>132:
        script=' '.join(_words(script)[:130])+'.'
    return {
        'script':script,
        'hook':hook,
        'title':str(project.get('title') or f'{topic}: The Detail Most People Miss').strip()[:78],
        'word_count':len(_words(script)),
        'model':'source-backed-retention-writer-v2',
        'source':source,
    }
