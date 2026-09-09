import hashlib
import json
import os
import random
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

from production_guard import creative_preflight

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
if not SUPABASE_URL or not SERVICE_KEY:
    raise SystemExit('Supabase secrets required.')
HEADERS = {'apikey': SERVICE_KEY, 'Authorization': f'Bearer {SERVICE_KEY}', 'Content-Type': 'application/json'}


def req(method, path, data=None, prefer=None):
    body = None if data is None else json.dumps(data).encode()
    headers = dict(HEADERS)
    if prefer:
        headers['Prefer'] = prefer
    request = urllib.request.Request(SUPABASE_URL + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        return json.loads(raw.decode()) if raw else None


def seed_for(series_id, episode_number):
    return int(hashlib.sha256(f'{series_id}:{episode_number}'.encode()).hexdigest()[:16], 16)


def choose(rng, items):
    return items[rng.randrange(len(items))]


def episodes(series_id):
    return req('GET', f'/rest/v1/series_episodes?series_id=eq.{series_id}&select=*&order=episode_number.asc') or []


def project_status(project_id):
    if not project_id:
        return None
    rows = req('GET', f'/rest/v1/video_projects?id=eq.{project_id}&select=id,status,title&limit=1') or []
    return rows[0] if rows else None


def prior_episode(series_id):
    rows = req('GET', f'/rest/v1/series_episodes?series_id=eq.{series_id}&select=episode_number,chapter_title,synopsis,continuity,video_project_id,status&order=episode_number.desc&limit=1') or []
    return rows[0] if rows else None


def ensure_master(series):
    bible = series.get('story_bible') or {}
    master = bible.get('master_story') or {}
    if not master:
        raw_chars = bible.get('characters') or ['Mara', 'Jax', 'Niko', 'Vale']
        chars = [str(c.get('name') if isinstance(c, dict) else c) for c in raw_chars]
        master = {
            'logline': f"{series['premise']} One continuous escalating story follows {', '.join(chars[:5])} as every discovery changes the next choice.",
            'central_question': 'What is really happening, who can be trusted, and what will the characters sacrifice to reach the truth?',
            'acts': [
                {'name': 'Act I — Discovery', 'range': [1, 20]},
                {'name': 'Act II — Escalation', 'range': [21, 45]},
                {'name': 'Act III — Fracture', 'range': [46, 70]},
                {'name': 'Act IV — Reckoning', 'range': [71, 90]},
                {'name': 'Act V — Resolution', 'range': [91, 100]},
            ],
            'open_threads': ['the central mystery', 'the cost of the first discovery', 'a trust fracture inside the group'],
            'resolved_threads': [],
            'ending': 'Resolve the central mystery and major character promises after the final act.',
        }
        bible['master_story'] = master
    return bible, master


def character_names(bible):
    raw = bible.get('characters') or ['Mara', 'Jax', 'Niko', 'Vale']
    names = []
    for item in raw:
        name = str(item.get('name') if isinstance(item, dict) else item).strip()
        if name:
            names.append(name)
    return names or ['Mara', 'Jax', 'Niko', 'Vale']


def act_for(master, number):
    for act in master.get('acts', []):
        low, high = act.get('range', [1, 100])
        if low <= number <= high:
            return act.get('name', 'Continuing arc')
    return 'Continuing arc'


def clip_words(text, limit):
    words = str(text or '').split()
    clipped = ' '.join(words[:limit]).strip(' ,;:')
    if clipped and clipped[-1:] not in '.?!':
        clipped += '.'
    return clipped


def animated_story(series, episode_number):
    rng = random.Random(seed_for(series['id'], episode_number))
    bible, master = ensure_master(series)
    chars = character_names(bible)
    lead = chars[(episode_number - 1) % len(chars)]
    ally = chars[episode_number % len(chars)]
    previous = prior_episode(series['id'])
    carry = (previous or {}).get('continuity') or bible.get('last_continuity') or {}
    prior = carry.get('cliffhanger') or carry.get('open_loop') or 'the discovery they barely escaped with'
    act = act_for(master, episode_number)
    places = ['the flooded observation dome', 'the bioluminescent market', 'the old tide-control tunnels', 'the abandoned research pier', 'the deep-water transit lock', 'the storm-lit harbor wall', 'the sealed archive below the marina', 'the reef beyond the warning buoys']
    place = choose(rng, places)
    thread = choose(rng, master.get('open_threads') or ['the central mystery'])
    turn = choose(rng, ['evidence that contradicts the safest explanation', 'a clue everyone dismissed earlier', 'proof a trusted story cannot be true', 'a warning that is actually a map', 'a hidden record that changes who can be trusted', 'a device reacting to an unexpected name'])
    chapter_name = choose(rng, ['The Signal Below', 'A Door That Should Not Open', 'The Missing Current', 'What the Lights Remember', 'The Name in the Archive', 'Pressure Line', 'The False Safe Harbor', 'The Last Quiet Warning'])
    title = f'Chapter {episode_number}: {chapter_name}'
    cliff = f'A final detail links {thread} to {ally}, forcing {lead} into a dangerous choice in Chapter {episode_number + 1}.'
    hook = f'{lead} reaches {place} expecting an answer, but the clue waiting there makes the last danger worse.'
    script = ' '.join([
        hook,
        f'The group is still carrying this consequence: {clip_words(prior, 16)}',
        f'{ally} urges caution while {lead} notices {turn}, pointing the mystery back toward {thread}.',
        'They test the clue, lose one safe route, and prove the new evidence is connected to what happened before.',
        f'An earlier detail changes meaning, forcing {lead} to question an explanation the group trusted.',
        f'Meanwhile, {ally} realizes the evidence can protect the team or expose the truth, but it cannot do both.',
        f'Inside {act}, they keep moving because stopping now would leave the most important question unanswered.',
        clip_words(cliff, 20),
    ])
    continuity = {
        'chapter': episode_number,
        'act': act,
        'lead': lead,
        'ally': ally,
        'location': place,
        'advanced_thread': thread,
        'previous_cliffhanger': prior,
        'cliffhanger': cliff,
        'open_loop': cliff,
        'master_logline': master.get('logline'),
        'shot_plan': {'location': place, 'required_character_consistency': [lead, ally], 'payoff_previous': True, 'ending_handoff': True},
    }
    synopsis = f'{lead} follows the previous consequence into {place}, where new evidence advances {thread} and creates the choice that drives the next chapter.'
    return title, synopsis, hook, script, continuity, bible


def documentary_story(series, episode_number):
    bible, master = ensure_master(series)
    facts = bible.get('verified_facts') or []
    if not facts:
        raise RuntimeError('Documentary series needs story_bible.verified_facts before automatic factual episode generation.')
    rng = random.Random(seed_for(series['id'], episode_number))
    fact = facts[(episode_number - 1) % len(facts)]
    fact_text = str((fact.get('fact') or fact.get('claim')) if isinstance(fact, dict) else fact).strip()
    source = str(fact.get('source') or '') if isinstance(fact, dict) else ''
    previous = prior_episode(series['id'])
    prior = ((previous or {}).get('continuity') or {}).get('open_loop') or 'the consequence established in the previous chapter'
    act = act_for(master, episode_number)
    title = f'Chapter {episode_number}: {choose(rng, ["The Detail That Changes Everything", "The Hidden Turning Point", "The Consequence", "What Happened Next"])}'
    hook = 'The important part of this story is what the next verified detail forced to happen.'
    script = ' '.join([
        hook,
        f'The previous chapter left one consequence unresolved: {clip_words(prior, 15)}',
        f'The verified record gives the next solid piece: {fact_text}',
        'That evidence matters because it changes the same timeline instead of starting a new subject.',
        'Following cause and consequence narrows the possibilities and rules out an easy explanation.',
        f'Inside {act}, the source stays traceable while uncertain details remain uncertain.',
        'The next chapter follows the direct verified consequence of this event.',
    ])
    continuity = {
        'fact': fact_text,
        'source': source,
        'act': act,
        'open_loop': 'Follow the direct verified consequence in the next chapter.',
        'master_logline': master.get('logline'),
        'shot_plan': {'evidence_led': True, 'source': source, 'timeline_continuity': True},
    }
    return title, 'A connected evidence-led chapter in the same long-form documentary narrative.', hook, script, continuity, bible


def hold_until_prior_posts(series, latest, latest_project):
    now = datetime.now(timezone.utc)
    expected_next = int(latest['episode_number']) + 1 if latest else 1
    req('PATCH', f"/rest/v1/series_projects?id=eq.{series['id']}", {
        'next_episode_number': expected_next,
        'next_run_at': (now + timedelta(hours=1)).isoformat(),
        'updated_at': now.isoformat(),
    }, 'return=minimal')
    label = latest_project.get('title') if latest_project else f"chapter {latest.get('episode_number') if latest else '?'}"
    state = latest_project.get('status') if latest_project else 'missing'
    print(f"Series {series['title']} waiting: {label} is {state}; no later chapter will be generated until it is posted.")


def generate_one(series):
    existing = episodes(series['id'])
    latest = existing[-1] if existing else None
    latest_project = project_status(latest.get('video_project_id')) if latest else None
    if latest and (not latest_project or latest_project.get('status') != 'posted'):
        hold_until_prior_posts(series, latest, latest_project)
        return

    episode_number = (int(latest['episode_number']) + 1) if latest else 1
    if series['series_type'] == 'documentary':
        chapter, synopsis, hook, script, continuity, bible = documentary_story(series, episode_number)
    else:
        chapter, synopsis, hook, script, continuity, bible = animated_story(series, episode_number)

    probe = {
        'title': f"{series['title']} — {chapter}",
        'script': script,
        'hook': hook,
        'format': 'Story',
        'style': 'Documentary' if series['series_type'] == 'documentary' else 'Storytime',
        'target_duration_seconds': series['episode_length_seconds'],
    }
    preflight = creative_preflight(probe)
    if not preflight['passed']:
        raise RuntimeError('Generated chapter failed creative preflight before project creation: ' + '; '.join(preflight['reasons']))

    project = (req('POST', '/rest/v1/video_projects', {
        'user_id': series['user_id'],
        'title': probe['title'],
        'topic': synopsis,
        'format': probe['format'],
        'style': probe['style'],
        'target_duration_seconds': series['episode_length_seconds'],
        'status': 'generating',
        'hook': hook,
        'script': script,
        'creative_score': preflight['score'],
    }, 'return=representation') or [None])[0]
    if not project:
        raise RuntimeError('Could not create episode video project.')

    req('POST', '/rest/v1/series_episodes', {
        'user_id': series['user_id'],
        'series_id': series['id'],
        'episode_number': episode_number,
        'chapter_title': chapter,
        'synopsis': synopsis,
        'script': script,
        'continuity': continuity,
        'video_project_id': project['id'],
        'status': 'generating',
    }, 'return=minimal')

    steps = []
    for step, status, detail in [
        ('research', 'running' if series['series_type'] == 'documentary' else 'passed', 'Master story and continuity loaded.'),
        ('script', 'passed', 'Finished spoken narration advances the master story; production directions remain in continuity metadata only.'),
        ('creative_preflight', 'passed', f"Generation-time creative preflight passed at {preflight['score']}/100."),
        ('voice', 'pending', 'Queued for expressive narration.'),
        ('visuals', 'pending', 'Queued for motion-first scene planning.'),
        ('edit', 'pending', 'Queued for retention-focused edit.'),
        ('sound_design', 'pending', 'Sound design runs after picture lock.'),
        ('final_video_qc', 'pending', 'Finished MP4 must pass before publishing.'),
        ('quality_check', 'pending', None),
        ('ready', 'pending', None),
    ]:
        steps.append({'user_id': series['user_id'], 'project_id': project['id'], 'step': step, 'status': status, 'detail': detail})
    req('POST', '/rest/v1/project_pipeline_steps', steps, 'resolution=merge-duplicates,return=minimal')
    req('POST', '/rest/v1/hook_variants', {'user_id': series['user_id'], 'project_id': project['id'], 'hook': hook, 'selected': True}, 'return=minimal')
    req('POST', '/rest/v1/render_jobs', {'user_id': series['user_id'], 'project_id': project['id'], 'status': 'queued', 'engine': 'series-continuity'}, 'return=minimal')

    now = datetime.now(timezone.utc)
    bible['last_continuity'] = continuity
    req('PATCH', f"/rest/v1/series_projects?id=eq.{series['id']}", {
        'next_episode_number': episode_number + 1,
        'last_generated_at': now.isoformat(),
        'next_run_at': (now + timedelta(days=1)).isoformat(),
        'story_bible': bible,
        'updated_at': now.isoformat(),
    }, 'return=minimal')
    print(f"Queued connected {series['title']} chapter {episode_number}: {chapter}")


now = urllib.parse.quote(datetime.now(timezone.utc).isoformat(), safe='')
series_rows = req('GET', f'/rest/v1/series_projects?status=eq.active&cadence=eq.daily&or=(next_run_at.is.null,next_run_at.lte.{now})&select=*&order=created_at.asc') or []
if not series_rows:
    print('No due series episodes.')
else:
    for item in series_rows:
        try:
            generate_one(item)
        except Exception as exc:
            print(f"Series {item.get('id')} skipped: {exc}")
