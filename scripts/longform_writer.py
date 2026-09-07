import json, os, re, urllib.request

API_KEY=os.environ.get('OPENAI_API_KEY','').strip()
MODEL=os.environ.get('ROLIXA_WRITER_MODEL','gpt-5.6')

def _words(text): return re.findall(r"[A-Za-z0-9']+",str(text or ''))
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

def write(project, evidence=None):
    if not API_KEY: raise RuntimeError('OPENAI_API_KEY is required for autonomous long-form writing.')
    seconds=max(300,int(project.get('target_duration_seconds') or 600)); target=int(seconds*2.05)
    topic=str(project.get('topic') or project.get('title') or 'Untitled topic').strip(); style=str(project.get('style') or 'Documentary')
    sources='\n'.join(f"- {x.get('title','Source')}: {x.get('claim','')} ({x.get('url','')})" for x in (evidence or []) if x.get('verified')) or 'No verified factual source packet was supplied. Do not invent precise factual claims; write as narrative/analysis and clearly avoid unsupported specifics.'
    instructions=f'''You are the senior long-form YouTube writer for a high-retention production system. Write the FINAL SPOKEN NARRATION only, not an outline and not production directions.\n\nTopic: {topic}\nWorking title: {project.get('title') or topic}\nStyle: {style}\nTarget runtime: {seconds//60} minutes\nTarget length: about {target} words\n\nVerified source packet:\n{sources}\n\nRequirements:\n- Open with a 1-2 sentence cold open that creates a specific unanswered question.\n- Build a coherent beginning, escalation, midpoint reversal/reframe, deeper consequence, and satisfying payoff.\n- Every 45-75 seconds introduce a new question, contrast, example, consequence, or reveal.\n- Vary sentence length and paragraph rhythm for natural narration.\n- No filler, greetings, channel promotion, generic hype, fake quotes, invented facts, stage directions, SCENE labels, camera directions, citations read aloud, or internal brand names.\n- Explain difficult ideas concretely before using jargon.\n- If evidence is limited, narrow the claim instead of guessing.\n- End with a memorable resolution that answers the opening question and leaves one natural thought for the viewer.\n- Return only the narration text.'''
    body={'model':MODEL,'input':instructions,'max_output_tokens':min(16000,max(5000,int(target*1.7)))}
    req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(body).encode(),headers={'Authorization':f'Bearer {API_KEY}','Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=600) as r: payload=json.loads(r.read().decode())
    text=_output_text(payload).strip()
    if len(_words(text))<max(750,target*.62): raise RuntimeError(f'Writer returned only {len(_words(text))} words; refusing thin long-form script.')
    return {'script':text,'hook':re.split(r'(?<=[.!?])\s+',text)[0][:240],'word_count':len(_words(text)),'model':MODEL}
