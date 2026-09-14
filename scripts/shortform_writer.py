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
HOOK_SIGNAL=re.compile(r'(?i)(\?|\bwhy\b|\bhow\b|\bbut\b|\bproblem\b|\bcost\b|\bpaid\b|\bsuddenly\b|\bhidden\b|\bchanged\b|\bnever\b|\buntil\b|\bdoor\b|\bvoice\b|\bfound\b)')


def _words(text):
    return re.findall(r"[A-Za-z0-9']+",str(text or ''))


def _clean_spoken(text):
    text=str(text or '')
    text=re.sub(r'\[[^\]]+\]','',text)
    text=re.sub(r'\([^)]{24,}\)','',text)
    text=text.replace('—',', ').replace('–','-')
    text=re.sub(r'\s+',' ',text).strip()
    text=re.sub(r'\s+([,.;:!?])',r'\1',text)
    text=re.sub(r'([,.;:!?])(?=[A-Za-z0-9])',r'\1 ',text)
    return text


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


def _spoken_sentences(text):
    clean=_clean_spoken(text)
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+',clean) if len(_words(s))>=3]


def _readability_ok(script):
    parts=_spoken_sentences(script)
    if len(parts)<6:
        return False
    lengths=[len(_words(s)) for s in parts]
    if any(n>24 for n in lengths):
        return False
    if sum(1 for n in lengths if n<4)>1:
        return False
    normalized=[re.sub(r'\W+',' ',s.lower()).strip() for s in parts]
    if len(set(normalized))!=len(normalized):
        return False
    return True


def needs_script(project):
    fmt=str(project.get('format') or '').lower()
    target=int(project.get('target_duration_seconds') or 60)
    if fmt not in ('short','shorts','story','fiction','fictional','narrative') or target>120:
        return False
    script=str(project.get('script') or '').strip()
    hook=str(project.get('hook') or '').strip()
    low=script.lower()
    weak_hook=(len(_words(hook))<5 or len(_words(hook))>18 or not HOOK_SIGNAL.search(hook))
    return (
        len(_words(script))<_target_min_words(project)
        or any(marker in low for marker in GENERIC_MARKERS)
        or weak_hook
        or not _readability_ok(script)
    )


def _source(topic):
    params=urllib.parse.urlencode({
        'action':'query','generator':'search','gsrsearch':topic,'gsrlimit':'5',
        'prop':'extracts|info','explaintext':'1','exchars':'6500','inprop':'url',
        'format':'json','formatversion':'2'
    })
    req=urllib.request.Request('https://en.wikipedia.org/w/api.php?'+params,headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=25) as response:
        data=json.loads(response.read().decode())
    pages=((data.get('query') or {}).get('pages') or [])
    ranked=[]
    for page in pages:
        extract=_clean_spoken(page.get('extract') or '')
        ranked.append((len(_words(extract)),page,extract))
    ranked.sort(key=lambda row:row[0],reverse=True)
    if not ranked or ranked[0][0]<55:
        raise RuntimeError('No sufficiently detailed public reference found for this Short topic.')
    _,page,extract=ranked[0]
    return {'title':str(page.get('title') or topic),'url':str(page.get('fullurl') or ''),'extract':extract}


def _sentences(text):
    return [s for s in _spoken_sentences(text) if len(_words(s))>=6]


def _trim_sentence(sentence,max_words):
    s=_clean_spoken(sentence)
    ws=s.split()
    if len(ws)>max_words:
        cut=ws[:max_words]
        while cut and cut[-1].lower().rstrip(',;:') in ('and','or','but','because','while','which','that','with','of','to'):
            cut=cut[:-1]
        s=' '.join(cut).rstrip(',;:')
    if not s.endswith(('.', '!', '?')):
        s+='.'
    return s


def _compact_claim(sentence,index):
    s=_trim_sentence(sentence,17 if index<2 else 20)
    if index==0:
        return s
    transitions=(
        'That matters because ',
        'The next detail is ',
        'More importantly, ',
        'The result is ',
        'And that means ',
    )
    lower=s[0].lower()+s[1:] if len(s)>1 else s.lower()
    prefix=transitions[(index-1)%len(transitions)]
    combined=prefix+lower
    return _trim_sentence(combined,22)


def _make_hook(project,topic):
    current=_clean_spoken(project.get('hook') or '')
    if 5<=len(_words(current))<=18 and HOOK_SIGNAL.search(current):
        return _trim_sentence(current,18)
    topic_words=' '.join(_words(topic)[:8])
    return f'Why is {topic_words} more surprising than it sounds?'


def _fiction_hook(project,topic):
    current=_clean_spoken(project.get('hook') or '')
    if 5<=len(_words(current))<=18 and re.search(r'(?i)(\?|\bbut\b|\bnever\b|\buntil\b|\bfound\b|\bhidden\b|\bchanged\b)',current):
        return _trim_sentence(current,18)
    title=str(project.get('title') or topic).strip()
    subtitle=title.split(':')[-1].strip(' —-') if ':' in title else title.split('—')[-1].strip()
    key=' '.join(_words(subtitle)[:7]) or 'the next clue'
    return f'But {key} was only the beginning.'


def _fiction_seed(project,topic):
    for key in ('description','concept','prompt','summary','premise'):
        value=_clean_spoken(project.get(key) or '')
        if len(_words(value))>=6:
            return value
    return topic


def _story_parts(seed):
    clean=_clean_spoken(seed)
    protagonist=(_words(clean) or ['Someone'])[0]
    location='the next place'
    match=re.search(r'(?i)\binto the ([^,.;!?]+)',clean)
    if match:
        location='the '+match.group(1).strip()
    consequence='the mystery'
    match=re.search(r'(?i)\badvances? ([^,.;!?]+)',clean)
    if match:
        consequence=match.group(1).strip()
    return protagonist,location,consequence


def _write_fiction(project,topic):
    hook=_fiction_hook(project,topic)
    seed=_fiction_seed(project,topic)
    protagonist,location,consequence=_story_parts(seed)
    beats=[
        f'{protagonist} entered {location} expecting one answer, but found a contradiction instead.',
        'A familiar detail appeared in the wrong place, so the earlier warning suddenly felt real.',
        f'Then {consequence} pointed toward someone inside the group.',
        'No one agreed on what the clue meant, and their trust started to crack.',
        f'{protagonist} had to choose between retreating safely and following the clue before it disappeared.',
        'They followed it, and the place behind them locked shut.',
    ]
    closing='That choice changed what the group believed the mystery was really about.'
    target_min=_target_min_words(project)
    padding=[
        f'One overlooked detail in {location} made the danger feel deliberate instead of accidental.',
        f'Worse, the clue tied {consequence} to a consequence nobody had prepared for.',
        f'By then, {protagonist} could no longer dismiss the discovery as coincidence.',
    ]
    clean_beats=[_trim_sentence(x,22) for x in beats]
    script=' '.join([hook]+clean_beats+[closing])
    for beat in padding:
        if len(_words(script))>=target_min:
            break
        clean_beats.append(_trim_sentence(beat,22))
        script=' '.join([hook]+clean_beats+[closing])
    if not _readability_ok(script):
        raise RuntimeError('Generated fiction narration failed coherence/readability checks.')
    title=str(project.get('title') or topic).strip()[:78]
    return {
        'script':script,
        'hook':hook,
        'title':title,
        'word_count':len(_words(script)),
        'model':'original-fiction-retention-writer-v4-coherent',
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
    closing=f'That is why {" ".join(_words(topic)[:7])} matters more than the headline suggests.'
    desired=_target_min_words(project)
    closing_words=len(_words(closing))
    claims=[]
    total=len(_words(hook))
    soft_cap=max(118,desired+28)
    for sentence in source_sentences[:14]:
        claim=_compact_claim(sentence,len(claims))
        n=len(_words(claim))
        if claims and total+n+closing_words>soft_cap:
            break
        claims.append(claim)
        total+=n
        if total+closing_words>=desired and len(claims)>=4:
            break
    if len(claims)<4 or total+closing_words<desired:
        raise RuntimeError(f'Source could not support the {desired}-word publish-grade narration floor for this Short.')
    script=' '.join([hook]+claims+[_trim_sentence(closing,20)])
    if not _readability_ok(script):
        raise RuntimeError('Generated factual narration failed coherence/readability checks.')
    return {
        'script':script,
        'hook':hook,
        'title':str(project.get('title') or f'{topic}: The Detail Most People Miss').strip()[:78],
        'word_count':len(_words(script)),
        'model':'source-backed-retention-writer-v4-coherent',
        'source':source,
        'fictional':False,
    }
