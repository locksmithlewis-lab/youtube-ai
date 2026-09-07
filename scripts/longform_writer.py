import json, os, re, urllib.request

API_KEY=os.environ.get('OPENAI_API_KEY','').strip()
MODEL=os.environ.get('ROLIXA_WRITER_MODEL','gpt-5.6')


def _words(text): return re.findall(r"[A-Za-z0-9']+",str(text or ''))
def _sentences(text): return [x.strip() for x in re.split(r'(?<=[.!?])\s+',str(text or '')) if x.strip()]
def is_longform(project): return int(project.get('target_duration_seconds') or 0)>=180 or str(project.get('format') or '').lower() in ('long','longform','full','youtube','youtube video','full video','long form','long-form')
def needs_script(project):
    if not is_longform(project): return False
    target=max(900,int(project.get('target_duration_seconds') or 600)*1.75)
    return len(_words(project.get('script'))) < target*.78


def _output_text(payload):
    if payload.get('output_text'): return payload['output_text']
    parts=[]
    for item in payload.get('output') or []:
        for c in item.get('content') or []:
            if c.get('type') in ('output_text','text') and c.get('text'): parts.append(c['text'])
    return '\n'.join(parts).strip()


def _evidence_lines(evidence):
    out=[]
    for x in evidence or []:
        if not x.get('verified'): continue
        claim=re.sub(r'\s+',' ',str(x.get('claim') or '')).strip()
        title=re.sub(r'\s+',' ',str(x.get('title') or 'verified source')).strip()
        if claim: out.append((title,claim))
    return out


def _offline_paragraphs(topic,style,evidence,target):
    facts=_evidence_lines(evidence)
    fact_text=[c for _,c in facts]
    factual=bool(facts)
    safe_basis=(fact_text if fact_text else [
        f'The central subject is {topic}, and the useful question is what can be understood from the information already available.',
        f'Without a verified source packet, the discussion around {topic} has to stay analytical rather than pretending uncertain details are facts.'
    ])
    hooks=[
        f'{topic} seems simple until one question changes the way the whole subject looks: what is actually driving it?',
        f'The most interesting part of {topic} is not the obvious surface detail. It is the chain of causes and consequences underneath it.'
    ]
    frames=[
        ('Set the problem',f'To understand {topic}, start with the part that is easiest to miss. A headline, trend, invention, event, or idea can look self-explanatory while the real explanation sits one layer deeper. The goal here is to separate what is directly supported from what is merely assumed.'),
        ('Establish the evidence',f'The strongest place to begin is the evidence that can actually be defended. {{FACT}} That matters because it gives the story a fixed point. From there, the rest of the explanation can be built without turning uncertainty into confidence.'),
        ('Explain the mechanism',f'Once that anchor is clear, the next question is mechanism: how does {topic} produce the result people notice? The answer usually comes from a sequence rather than a single cause. One condition creates another, that second condition changes the incentives or environment, and the visible outcome arrives last.'),
        ('Add contrast',f'A useful way to see the pattern is to compare what people expect with what actually follows. The expected version of {topic} is usually neat and linear. The real version has tradeoffs, delays, feedback loops, or hidden constraints. That difference is where the story becomes more than a list of facts.'),
        ('Midpoint reframe',f'Here is the midpoint shift: the important question is no longer simply what {topic} is. The better question is what changes once people react to it. Attention, behavior, technology, money, risk, culture, or environment can all feed back into the original situation and reshape it.'),
        ('Consequences',f'That feedback creates consequences. Some are immediate and easy to see. Others only become visible after the system has had time to respond. The useful distinction is between short-term spectacle and long-term effect, because those two are often confused.'),
        ('Second evidence anchor',f'Another verified or carefully limited point helps keep the story grounded. {{FACT}} Instead of treating that statement as the ending, use it as a test: what explanation best fits it, and what explanations would require evidence we do not have?'),
        ('Human meaning',f'For a viewer, this is where {topic} becomes practical. The subject matters because it changes what someone notices, expects, chooses, fears, builds, watches, or prepares for. A strong explanation should make the viewer better at recognizing the pattern the next time it appears.'),
        ('Resolution',f'The answer to the opening question is that {topic} is best understood as a chain rather than a single moment. The visible result gets attention, but the hidden sequence explains why it happened. That distinction is the part worth remembering, because it turns a passing subject into something understandable.')
    ]
    out=[hooks[0]]
    i=0
    fact_i=0
    transitions=['Now take that one step further.','There is another layer.','This is where the pattern gets more interesting.','A different angle makes the same point clearer.','The next part matters because it changes the interpretation.','That leads to a harder question.']
    while len(_words(' '.join(out)))<target:
        _,base=frames[i%len(frames)]
        fact=safe_basis[fact_i%len(safe_basis)]
        if '{{FACT}}' in base: fact_i+=1
        para=base.replace('{{FACT}}',fact)
        if i>=len(frames): para=transitions[i%len(transitions)]+' '+para
        if not factual and i%4==1:
            para+=' Because verified sourcing is limited, this section stays with explanation and clearly bounded inference instead of adding precise names, dates, statistics, or quotes.'
        out.append(para)
        i+=1
        if i>42: break
    text='\n\n'.join(out)
    ws=_words(text)
    if len(ws)>target*1.18:
        cutoff=int(target*1.12)
        text=' '.join(ws[:cutoff])
        if text and text[-1] not in '.!?': text+='.'
    return text


def _write_offline(project,evidence=None):
    seconds=max(300,int(project.get('target_duration_seconds') or 600)); target=max(900,int(seconds*1.9))
    topic=str(project.get('topic') or project.get('title') or 'Untitled topic').strip(); style=str(project.get('style') or 'Documentary')
    text=_offline_paragraphs(topic,style,evidence,target)
    count=len(_words(text))
    if count<max(750,target*.62): raise RuntimeError(f'Offline writer produced only {count} words; refusing thin long-form script.')
    first=_sentences(text)[0] if _sentences(text) else topic
    return {'script':text,'hook':first[:240],'word_count':count,'model':'offline-structured-writer-v1'}


def _write_openai(project,evidence=None):
    seconds=max(300,int(project.get('target_duration_seconds') or 600)); target=int(seconds*2.05)
    topic=str(project.get('topic') or project.get('title') or 'Untitled topic').strip(); style=str(project.get('style') or 'Documentary')
    sources='\n'.join(f"- {x.get('title','Source')}: {x.get('claim','')} ({x.get('url','')})" for x in (evidence or []) if x.get('verified')) or 'No verified factual source packet was supplied. Do not invent precise factual claims; write as narrative/analysis and clearly avoid unsupported specifics.'
    instructions=f'''You are the senior long-form YouTube writer for a high-retention production system. Write the FINAL SPOKEN NARRATION only, not an outline and not production directions.\n\nTopic: {topic}\nWorking title: {project.get('title') or topic}\nStyle: {style}\nTarget runtime: {seconds//60} minutes\nTarget length: about {target} words\n\nVerified source packet:\n{sources}\n\nRequirements:\n- Open with a 1-2 sentence cold open that creates a specific unanswered question.\n- Build a coherent beginning, escalation, midpoint reversal/reframe, deeper consequence, and satisfying payoff.\n- Every 45-75 seconds introduce a new question, contrast, example, consequence, or reveal.\n- Vary sentence length and paragraph rhythm for natural narration.\n- No filler, greetings, channel promotion, generic hype, fake quotes, invented facts, stage directions, SCENE labels, camera directions, citations read aloud, or internal brand names.\n- Explain difficult ideas concretely before using jargon.\n- If evidence is limited, narrow the claim instead of guessing.\n- End with a memorable resolution that answers the opening question and leaves one natural thought for the viewer.\n- Return only the narration text.'''
    body={'model':MODEL,'input':instructions,'max_output_tokens':min(16000,max(5000,int(target*1.7)))}
    req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(body).encode(),headers={'Authorization':f'Bearer {API_KEY}','Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=600) as r: payload=json.loads(r.read().decode())
    text=_output_text(payload).strip(); count=len(_words(text))
    if count<max(750,target*.62): raise RuntimeError(f'Writer returned only {count} words; refusing thin long-form script.')
    return {'script':text,'hook':_sentences(text)[0][:240],'word_count':count,'model':MODEL}


def write(project,evidence=None):
    if API_KEY:
        try: return _write_openai(project,evidence)
        except Exception as exc:
            fallback=_write_offline(project,evidence)
            fallback['model']='offline-structured-writer-v1 (OpenAI fallback: '+str(exc)[:120]+')'
            return fallback
    return _write_offline(project,evidence)
