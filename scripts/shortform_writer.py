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
)


def _words(text):
    return re.findall(r"[A-Za-z0-9']+",str(text or ''))


def needs_script(project):
    fmt=str(project.get('format') or '').lower()
    target=int(project.get('target_duration_seconds') or 60)
    if fmt not in ('short','shorts','story') or target>120:
        return False
    script=str(project.get('script') or '').strip()
    low=script.lower()
    return len(_words(script))<55 or any(marker in low for marker in GENERIC_MARKERS)


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
    return {
        'title':str(page.get('title') or topic),
        'url':str(page.get('fullurl') or ''),
        'extract':extract,
    }


def _sentences(text):
    return [re.sub(r'\s+',' ',s).strip() for s in re.split(r'(?<=[.!?])\s+',text) if len(_words(s))>=6]


def _compact_claim(sentence,topic,index):
    s=re.sub(r'\[[^\]]+\]','',sentence).strip()
    s=re.sub(r'\([^)]{20,}\)','',s).strip()
    words=s.split()
    if len(words)>20:
        s=' '.join(words[:20]).rstrip(',;:')+'.'
    if not s.endswith(('.', '!', '?')):
        s+='.'
    # Change the sentence frame so the output is narration, not a pasted source paragraph.
    if index==0:
        return f'Here is the key fact about {topic}: {s[0].lower()+s[1:] if len(s)>1 else s.lower()}'
    frames=(
        'Another useful piece of the story is this: ',
        'The next detail adds context: ',
        'That leads to another sourced fact: ',
        'One more part is worth knowing: ',
    )
    return frames[(index-1)%len(frames)]+s[0].lower()+s[1:]


def write(project):
    topic=str(project.get('topic') or project.get('title') or '').strip()
    if len(_words(topic))<2:
        raise RuntimeError('Short topic is too vague to source and write automatically.')
    source=_source(topic)
    source_sentences=_sentences(source['extract'])
    claims=[]
    total=0
    for sentence in source_sentences[:8]:
        claim=_compact_claim(sentence,topic,len(claims))
        n=len(_words(claim))
        if claims and total+n>125:
            break
        claims.append(claim);total+=n
        if total>=92 and len(claims)>=4:
            break
    if len(claims)<4 or total<70:
        raise RuntimeError('Source could not support enough distinct narration beats for a publishable Short.')
    hook=claims[0]
    closing=f'Those details are why {topic} is worth understanding beyond the headline.'
    script=' '.join(claims+[closing])
    if len(_words(script))>140:
        script=' '.join(_words(script)[:138])+'.'
    return {
        'script':script,
        'hook':hook,
        'title':str(project.get('title') or f'{topic}: What Matters').strip()[:100],
        'word_count':len(_words(script)),
        'model':'source-backed-keyless-writer-v1',
        'source':source,
    }
