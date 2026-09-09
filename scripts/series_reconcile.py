import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from production_guard import creative_preflight, instruction_leaks

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
if not URL or not KEY:
    raise SystemExit("Supabase secrets required.")

HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}


def req(method, path, data=None, prefer=None):
    headers = dict(HEADERS)
    if prefer:
        headers["Prefer"] = prefer
    request = urllib.request.Request(
        URL + path,
        data=None if data is None else json.dumps(data).encode(),
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
            return json.loads(raw.decode()) if raw else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def patch(table, row_id, payload):
    return req("PATCH", f"/rest/v1/{table}?id=eq.{row_id}", payload, "return=minimal")


def step(project, name, status, detail):
    return req("POST", "/rest/v1/rpc/upsert_project_pipeline_step", {
        "p_user_id": project["user_id"],
        "p_project_id": project["id"],
        "p_step": name,
        "p_status": status,
        "p_detail": detail,
    })


def report(project, passed, score, reasons, metrics=None):
    return req("POST", "/rest/v1/video_quality_reports", {
        "user_id": project["user_id"],
        "project_id": project["id"],
        "stage": "series_continuity_repair",
        "passed": passed,
        "score": score,
        "reasons": reasons,
        "metrics": metrics or {},
    }, "return=minimal")


def get_project(project_id):
    rows = req("GET", f"/rest/v1/video_projects?id=eq.{project_id}&select=*") or []
    return rows[0] if rows else None


def get_episodes(series_id):
    return req(
        "GET",
        f"/rest/v1/series_episodes?series_id=eq.{series_id}&select=*&order=episode_number.asc",
    ) or []


def active_jobs(project_id):
    q = urllib.parse.urlencode({
        "project_id": f"eq.{project_id}",
        "status": "in.(queued,running,processing)",
        "select": "id,status,engine,updated_at",
        "order": "updated_at.desc",
    })
    return req("GET", "/rest/v1/render_jobs?" + q) or []


def queued_jobs(project_id):
    q = urllib.parse.urlencode({
        "project_id": f"eq.{project_id}",
        "status": "eq.queued",
        "select": "id,status,engine",
    })
    return req("GET", "/rest/v1/render_jobs?" + q) or []


def queue_job(project, engine="series-continuity"):
    if active_jobs(project["id"]):
        return False
    try:
        req("POST", "/rest/v1/render_jobs", {
            "user_id": project["user_id"],
            "project_id": project["id"],
            "engine": engine,
            "status": "queued",
        }, "return=minimal")
        return True
    except RuntimeError as exc:
        if "duplicate" in str(exc).lower() or "23505" in str(exc):
            return False
        raise


def map_episode_status(project_status):
    if project_status == "posted":
        return "posted"
    if project_status == "failed":
        return "failed"
    if project_status == "quality_check":
        return "quality_check"
    if project_status in ("ready", "scheduled", "publishing"):
        return "ready"
    return "generating"


def short_phrase(text, limit=18):
    tokens = str(text or "").strip().split()
    if not tokens:
        return ""
    clipped = " ".join(tokens[:limit]).strip(" ,;:")
    if clipped and clipped[-1:] not in ".?!":
        clipped += "."
    return clipped


def series_characters(series):
    bible = series.get("story_bible") or {}
    chars = bible.get("characters") or []
    cleaned = []
    for item in chars:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = ""
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def fiction_rewrite(series, episode, project, previous_episode=None):
    continuity = episode.get("continuity") or {}
    previous_continuity = (previous_episode or {}).get("continuity") or {}
    chars = series_characters(series)

    lead = str(continuity.get("lead") or (chars[0] if chars else "the lead")).strip()
    ally = str(continuity.get("ally") or "").strip()
    if not ally:
        ally = next((name for name in chars if name != lead), "their closest ally")
    location = str(continuity.get("location") or "the place tied to the last clue").strip()
    thread = str(
        continuity.get("advanced_thread")
        or continuity.get("mystery")
        or "the central mystery"
    ).strip()

    prior = str(
        continuity.get("previous_cliffhanger")
        or previous_continuity.get("cliffhanger")
        or previous_continuity.get("open_loop")
        or "the consequence left unresolved in the previous chapter"
    ).strip()
    cliff = str(
        continuity.get("cliffhanger")
        or continuity.get("open_loop")
        or f"the new evidence forces {lead} into a choice that cannot wait"
    ).strip()
    act = str(continuity.get("act") or "this part of the story").strip()

    prior_short = short_phrase(prior, 18)
    cliff_short = short_phrase(cliff, 20)

    lines = [
        f"{lead} reaches {location} expecting an answer, but the clue waiting there turns the last danger into a harder choice.",
        f"The group is still carrying this unresolved consequence: {prior_short}",
        f"{ally} argues for caution, while {lead} follows a detail that points back to {thread}.",
        "Testing that clue closes one safe route and proves the problem is connected to what the group already discovered.",
        f"That result changes what {lead} believes, because an earlier detail now means something different and someone they trusted looks less certain.",
        f"Meanwhile, {ally} notices the same evidence can protect the group or expose the truth, but it cannot do both.",
        f"Inside {act}, they choose to keep moving, knowing the next decision will carry a real cost into the following chapter.",
        cliff_short,
    ]
    script = " ".join(line for line in lines if line)
    hook = lines[0]
    candidate = dict(project, script=script, hook=hook)

    result = creative_preflight(candidate)
    if not result["passed"]:
        lines = [
            f"{lead} reaches {location} and finds evidence that makes the last danger worse.",
            f"The unresolved problem is still with them: {short_phrase(prior, 14)}",
            f"{ally} wants caution, but {lead} sees the clue pointing back to {thread}.",
            "They test it, lose one safe option, and prove the mystery is connected to what happened before.",
            f"An earlier detail changes meaning, forcing {lead} to question an explanation the group trusted.",
            f"{ally} realizes the evidence can protect the team or reveal the truth, but not both.",
            f"They move forward inside {act}, accepting that the choice will affect the next chapter.",
            short_phrase(cliff, 16),
        ]
        script = " ".join(line for line in lines if line)
        hook = lines[0]
        candidate = dict(project, script=script, hook=hook)
        result = creative_preflight(candidate)
    return candidate, result


def is_factual_series(series, project):
    return (
        str(series.get("series_type") or "").lower() == "documentary"
        or str(project.get("style") or "").lower() in ("documentary", "news", "educational", "explainer")
    )


def is_creative_failure(project):
    reason = str(project.get("failure_reason") or "").lower()
    markers = (
        "creative preflight",
        "script too",
        "production directions",
        "template phrasing",
        "narrative beats",
        "opening hook",
        "generic batch title",
        "sentences start the same way",
        "sentence rhythm",
        "vocabulary is too repetitive",
    )
    if any(marker in reason for marker in markers):
        return True
    return bool(instruction_leaks(str(project.get("script") or "")))


def is_mechanical_failure(project):
    reason = str(project.get("failure_reason") or "").lower()
    markers = (
        "visual", "motion", "image", "provider", "download", "429", "403",
        "timeout", "ffmpeg", "decode", "audio", "silence", "freeze",
        "black frame", "render", "duration", "size", "storage", "http error",
        "final video qc", "integrity",
    )
    return any(marker in reason for marker in markers)


def requeue(project, episode, engine, detail):
    now = datetime.now(timezone.utc).isoformat()
    attempts = int(project.get("qc_attempts") or 0)
    patch("video_projects", project["id"], {
        "status": "generating",
        "output_url": None,
        "scheduled_publish_at": None,
        "failure_reason": detail,
        "qc_attempts": attempts + 1,
        "updated_at": now,
    })
    patch("series_episodes", episode["id"], {
        "status": "generating",
        "updated_at": now,
    })
    project = dict(project, status="generating", qc_attempts=attempts + 1)
    queued = queue_job(project, engine)
    report(project, True, 70, [detail], {
        "episode_number": episode["episode_number"],
        "attempt": attempts + 1,
        "queued": queued,
    })
    return queued


def repair_barrier(series, episodes, barrier_index, project):
    episode = episodes[barrier_index]
    attempts = int(project.get("qc_attempts") or 0)
    if attempts >= 5:
        report(project, False, 0, ["series continuity repair limit reached"], {
            "episode_number": episode["episode_number"],
            "attempts": attempts,
            "failure": project.get("failure_reason"),
        })
        return "limit"

    if is_factual_series(series, project) and is_creative_failure(project):
        report(project, False, 20, ["documentary series needs verified-source rewrite before continuity repair"], {
            "episode_number": episode["episode_number"],
            "failure": project.get("failure_reason"),
        })
        return "waiting_source"

    if not is_factual_series(series, project) and is_creative_failure(project):
        previous_episode = episodes[barrier_index - 1] if barrier_index > 0 else None
        candidate, result = fiction_rewrite(series, episode, project, previous_episode)
        report(project, result["passed"], result["score"], result.get("reasons") or ["series script rebuilt"], {
            "episode_number": episode["episode_number"],
            "preflight": result,
            "old_failure": project.get("failure_reason"),
        })
        if not result["passed"]:
            return "rewrite_failed"
        now = datetime.now(timezone.utc).isoformat()
        patch("video_projects", project["id"], {
            "script": candidate["script"],
            "hook": candidate["hook"],
            "creative_score": result["score"],
            "status": "generating",
            "output_url": None,
            "scheduled_publish_at": None,
            "failure_reason": "Series continuity script rebuilt and queued for clean rerender.",
            "qc_attempts": attempts + 1,
            "updated_at": now,
        })
        patch("series_episodes", episode["id"], {
            "script": candidate["script"],
            "status": "generating",
            "updated_at": now,
        })
        refreshed = dict(project, **candidate, status="generating", qc_attempts=attempts + 1)
        step(refreshed, "script", "passed", "Series continuity controller rebuilt concise spoken narration while preserving the prior handoff and next cliffhanger.")
        step(refreshed, "creative_preflight", "passed", f"Series continuity rewrite passed creative preflight at {result['score']}/100.")
        queue_job(refreshed, "series-continuity-creative-repair")
        return "rewritten"

    if is_mechanical_failure(project):
        requeue(
            project,
            episode,
            "series-continuity-render-repair",
            f"Series continuity repair attempt {attempts + 1}: rerendering the earliest unpublished chapter before later chapters.",
        )
        return "requeued"

    report(project, False, 30, ["series barrier is not safely auto-repairable"], {
        "episode_number": episode["episode_number"],
        "failure": project.get("failure_reason"),
    })
    return "waiting"


series_rows = req(
    "GET",
    "/rest/v1/series_projects?status=eq.active&select=*&order=created_at.asc",
) or []

summary = {
    "series_checked": 0,
    "episode_status_synced": 0,
    "next_episode_fixed": 0,
    "later_jobs_held": 0,
    "barriers_queued": 0,
    "barriers_repaired": 0,
    "waiting": 0,
}

for series in series_rows:
    episodes = get_episodes(series["id"])
    if not episodes:
        continue
    summary["series_checked"] += 1
    projects = {}
    for episode in episodes:
        project = get_project(episode.get("video_project_id")) if episode.get("video_project_id") else None
        if project:
            projects[episode["id"]] = project
            expected = map_episode_status(project.get("status"))
            if episode.get("status") != expected:
                patch("series_episodes", episode["id"], {
                    "status": expected,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                episode["status"] = expected
                summary["episode_status_synced"] += 1

    expected_next = max(int(ep["episode_number"]) for ep in episodes) + 1
    if int(series.get("next_episode_number") or 1) != expected_next:
        patch("series_projects", series["id"], {
            "next_episode_number": expected_next,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        summary["next_episode_fixed"] += 1

    barrier_index = None
    barrier_project = None
    for index, episode in enumerate(episodes):
        project = projects.get(episode["id"])
        if not project or project.get("status") != "posted":
            barrier_index = index
            barrier_project = project
            break
    if barrier_index is None:
        continue

    for later in episodes[barrier_index + 1:]:
        later_project = projects.get(later["id"])
        if not later_project:
            continue
        for job in queued_jobs(later_project["id"]):
            patch("render_jobs", job["id"], {
                "status": "failed",
                "error": f"Series continuity hold: chapter {episodes[barrier_index]['episode_number']} must publish first.",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            summary["later_jobs_held"] += 1

    if not barrier_project:
        summary["waiting"] += 1
        continue

    status = barrier_project.get("status")
    if status == "generating":
        if queue_job(barrier_project, "series-continuity"):
            summary["barriers_queued"] += 1
    elif status == "failed":
        outcome = repair_barrier(series, episodes, barrier_index, barrier_project)
        if outcome in ("rewritten", "requeued"):
            summary["barriers_repaired"] += 1
        else:
            summary["waiting"] += 1
    elif status in ("quality_check", "ready", "scheduled", "publishing"):
        pass
    else:
        summary["waiting"] += 1

print(json.dumps(summary))
