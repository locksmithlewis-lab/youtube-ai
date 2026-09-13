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


def _is_fictional(project):
    fmt=str(project.get('format') or '').strip().lower()
    if fmt in ('story','fiction','fictional','narrative'):
        return True
    fields=('content_type','type','category','genre','style')
    text=' '.join(str(project.get(key) or '') for key in fields).lower()
    return bool(re.search(r'\b(fiction|fictional|story|narrative|screenplay|short story)\b',text))


def _target_min_words(project):
    target=max(1,int(project.get('target_duration_seconds') or 60))
    return max(55,int(target*1.7))


def needs_script(project):
    fmt=str(project.get('format') or '').lower()
    target=int(project.get('target_duration_seconds') or 60)
    if fmt not in ('short','shorts','story','fiction','fictional','narrative') or target>120:
        return False
    script=str(project.get('script') or '').strip()
    hook=str(project.get('hook') or '').strip()
    low=script.lower()
    weak_hook=(len(_words(hook))<5 or len(_words(hook))>18 or not re.search(r'(?i)(\?|\bwhy\b|\bhow\b|\bbut\b|\bproblem\b|\bcost\b|\bpaid\b|\bsuddenly\b|\bhidden\b|\bchanged\b|\bnever\b|\buntil\b|\bdoor\b|\bvoice\b|\bfound\b)',hook))
    return len(_words(script))<_target_min_words(project) or any(marker in low for marker in GENERIC_MARKERS) or weak_hook


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
    if 5<=len(_words(current))<=18 and re.search(r'(?i)(\?|\bwhy\b|\bhow\b|\bbut\b|\bproblem\b|\bcost\b|\bpaid\b|\bsuddenly\b|\bhidden\b|\bchanged\b|\bnever\b|\buntil\b|\bdoor\b|\bvoice\b|\bfound\b)',current):
        return current
    return f'Why does {topic} matter more than the headline makes it seem?'


def _fiction_hook(project,topic):
    current=re.sub(r'\s+',' ',str(project.get('hook') or '')).strip()
    if 5<=len(_words(current))<=18 and re.search(r'(?i)(\?|\bbut\b|\bnever\b|\buntil\b|\bfound\b|\bhidden\b|\bchanged\b)',current):
        return current
    title=str(project.get('title') or topic).strip()
    subtitle=title.split(':')[-1].strip(' —-') if ':' in title else title.split('—')[-1].strip()
    key=' '.join(_words(subtitle)[:7]) or 'the next clue'
    return f'But {key} was only the beginning.'


def _fiction_seed(project,topic):
    for key in ('description','concept','prompt','summary','premise'):
        value=re.sub(r'\s+',' ',str(project.get(key) or '')).strip()
        if len(_words(value))>=6:
            return value
    return topic


def _story_parts(seed):
    clean=re.sub(r'\s+',' ',seed).strip()
    protagonist=(_words(clean) or ['Someone'])[0]
    location='the next place'
    match=re.search(r'(?i)\binto the ([^,]+)',clean)
    if match:
        location='the '+match.group(1).strip()
    consequence='the mystery'
    match=re.search(r'(?i)\badvances? ([^,]+)',clean)
    if match:
        consequence=match.group(1).strip()
    return protagonist,location,consequence


def _write_fiction(project,topic):
    hook=_fiction_hook(project,topic)
    seed=_fiction_seed(project,topic)
    protagonist,location,consequence=_story_parts(seed)
    beats=[
        f'{protagonist} entered {location} expecting one answer, but found a contradiction instead.',
        'A familiar detail appeared in the wrong place, making the earlier warning impossible to dismiss.',
        f'Suddenly, {consequence} pointed toward someone inside the group.',
        'Nobody agreed on what the clue meant, and trust cracked before anyone could test it.',
        f'{protagonist} had one choice: retreat safely, or follow the clue before it disappeared.',
        'They followed it, and the place behind them locked shut.',
    ]
    closing='That decision changed what the group thought the mystery was really about.'
    target_min=_target_min_words(project)
    padding=[
        f'One overlooked detail in {location} made the danger feel deliberate rather than accidental.',
        f'Worse, the clue tied {consequence} to a consequence nobody in the group had prepared for.',
        f'By then, {protagonist} could no longer treat the discovery as a coincidence.',
    ]
    script=' '.join([hook]+beats+[closing])
    for beat in padding:
        if len(_words(script))>=target_min:
            break
        beats.append(beat)
        script=' '.join([hook]+beats+[closing])
    title=str(project.get('title') or topic).strip()[:78]
    return {
        'script':script,
        'hook':hook,
        'title':title,
        'word_count':len(_words(script)),
        'model':'original-fiction-retention-writer-v3',
        'source':None,
        'fictional':True,
    }


def write(project):
    topic=str(project.get('topic') or project.get('title') or '').strip()
    if len(_words(topic))<2:
        raise RuntimeError('Short topic is too vague to write automatically.')
    if _is_fictional(project):
        return _write_fiction(project,topic)
    source=_source(topic)
    source_sentences=_sentences(source['extract'])
    hook=_make_hook(project,topic)
    closing=f'That is the part of {topic} the headline alone does not explain.'
    desired=_target_min_words(project)
    closing_words=len(_words(closing))
    claims=[]
    total=len(_words(hook))
    soft_cap=max(118,desired+28)
    for sentence in source_sentences[:12]:
        claim=_compact_claim(sentence,len(claims))
        n=len(_words(claim))
        if claims and total+n+closing_words>soft_cap:
            break
        claims.append(claim);total+=n
        if total+closing_words>=desired and len(claims)>=4:
            break
    if len(claims)<4 or total+closing_words<desired:
        raise RuntimeError(f'Source could not support the {desired}-word publish-grade narration floor for this Short.')
    script=' '.join([hook]+claims+[closing])
    return {
        'script':script,
        'hook':hook,
        'title':str(project.get('title') or f'{topic}: The Detail Most People Miss').strip()[:78],
        'word_count':len(_words(script)),
        'model':'source-backed-retention-writer-v3',
        'source':source,
        'fictional':False,
    }
