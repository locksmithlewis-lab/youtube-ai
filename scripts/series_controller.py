"""Keep episodic series contiguous, repairable, and publish-ordered.

Only the earliest unpublished chapter in each active series is allowed to enter
rendering. Fiction script failures are rebuilt from stored continuity metadata;
factual series remain evidence-gated. Publishing order is also enforced by the
Supabase trigger, so this controller is an operational convenience rather than
the only safety barrier.
"""
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
ACTIVE_JOB_STATES = ("queued", "running", "processing")
CREATIVE_MARKERS = (
    "creative preflight", "script too", "production directions",
    "template phrasing", "narrative beats", "opening hook",
    "generic batch title", "sentences start the same way",
    "sentence rhythm", "vocabulary is too repetitive",
)
MECHANICAL_MARKERS = (
    "visual", "motion", "image", "provider", "download", "429", "403",
    "timeout", "ffmpeg", "decode", "audio", "silence", "freeze",
    "black frame", "render", "duration", "size", "storage", "http error",
    "final video qc", "integrity", "truncated",
)


def request(method, path, data=None, prefer=None):
    headers = dict(HEADERS)
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(
        URL + path,
        data=None if data is None else json.dumps(data).encode(),
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as res:
            raw = res.read()
            return json.loads(raw.decode()) if raw else None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:1200]
        except Exception:
            body = ""
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def patch(table, row_id, payload):
    return request("PATCH", f"/rest/v1/{table}?id=eq.{row_id}", payload, "return=minimal")


def get_project(project_id):
    if not project_id:
        return None
    rows = request("GET", f"/rest/v1/video_projects?id=eq.{project_id}&select=*") or []
    return rows[0] if rows else None


def episodes(series_id):
    return request(
        "GET",
        f"/rest/v1/series_episodes?series_id=eq.{series_id}&select=*&order=episode_number.asc",
    ) or []


def jobs(project_id, states=ACTIVE_JOB_STATES):
    status = "in.(" + ",".join(states) + ")"
    query = urllib.parse.urlencode({
        "project_id": f"eq.{project_id}",
        "status": status,
        "select": "id,status,engine,updated_at",
        "order": "updated_at.desc",
    })
    return request("GET", "/rest/v1/render_jobs?" + query) or []


def queue(project, engine):
    if jobs(project["id"]):
        return False
    try:
        request("POST", "/rest/v1/render_jobs", {
            "user_id": project["user_id"],
            "project_id": project["id"],
            "engine": engine,
            "status": "queued",
        }, "return=minimal")
        return True
    except RuntimeError as exc:
        text = str(exc).lower()
        if "23505" in text or "duplicate" in text:
            return False
        raise


def set_step(project, name, status, detail):
    request("POST", "/rest/v1/rpc/upsert_project_pipeline_step", {
        "p_user_id": project["user_id"],
        "p_project_id": project["id"],
        "p_step": name,
        "p_status": status,
        "p_detail": detail,
    })


def report(project, passed, score, reasons, metrics=None):
    request("POST", "/rest/v1/video_quality_reports", {
        "user_id": project["user_id"],
        "project_id": project["id"],
        "stage": "series_continuity_repair",
        "passed": passed,
        "score": score,
        "reasons": reasons,
        "metrics": metrics or {},
    }, "return=minimal")


def mapped_episode_status(project_status):
    if project_status == "posted":
        return "posted"
    if project_status == "failed":
        return "failed"
    if project_status == "quality_check":
        return "quality_check"
    if project_status in ("ready", "scheduled", "publishing"):
        return "ready"
    return "generating"


def factual(series, project):
    return (
        str(series.get("series_type") or "").lower() == "documentary"
        or str(project.get("style") or "").lower() in ("documentary", "news", "educational", "explainer")
    )


def has_creative_failure(project):
    reason = str(project.get("failure_reason") or "").lower()
    return any(marker in reason for marker in CREATIVE_MARKERS) or bool(
        instruction_leaks(str(project.get("script") or ""))
    )


def has_mechanical_failure(project):
    reason = str(project.get("failure_reason") or "").lower()
    return any(marker in reason for marker in MECHANICAL_MARKERS)


def clipped(text, words=16):
    tokens = str(text or "").strip().split()
    out = " ".join(tokens[:words]).strip(" ,;:")
    if out and out[-1:] not in ".?!":
        out += "."
    return out


def character_names(series):
    bible = series.get("story_bible") or {}
    values = bible.get("characters") or []
    names = []
    for value in values:
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip()
        else:
            name = str(value or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def rebuild_fiction(series, episode, project, previous_episode=None):
    continuity = episode.get("continuity") or {}
    previous = (previous_episode or {}).get("continuity") or {}
    names = character_names(series)
    lead = str(continuity.get("lead") or (names[0] if names else "the lead")).strip()
    ally = str(continuity.get("ally") or next((x for x in names if x != lead), "their closest ally")).strip()
    location = str(continuity.get("location") or "the place tied to the last clue").strip()
    thread = str(continuity.get("advanced_thread") or continuity.get("mystery") or "the central mystery").strip()
    prior = str(
        continuity.get("previous_cliffhanger")
        or previous.get("cliffhanger")
        or previous.get("open_loop")
        or "the consequence left unresolved in the previous chapter"
    ).strip()
    cliff = str(
        continuity.get("cliffhanger")
        or continuity.get("open_loop")
        or f"new evidence forces {lead} into a choice that cannot wait"
    ).strip()
    act = str(continuity.get("act") or "this part of the story").strip()

    variants = [
        [
            f"{lead} reaches {location} and finds evidence that makes the last danger worse.",
            f"The unresolved problem is still with them: {clipped(prior, 14)}",
            f"{ally} wants caution, but {lead} sees the clue pointing back to {thread}.",
            "They test it, lose one safe option, and prove the mystery is connected to what happened before.",
            f"An earlier detail changes meaning, forcing {lead} to question an explanation the group trusted.",
            f"Meanwhile, {ally} realizes the evidence can protect the team or reveal the truth, but not both.",
            f"Inside {act}, they move forward knowing the choice will affect the next chapter.",
            clipped(cliff, 16),
        ],
        [
            f"At {location}, {lead} expects an answer and instead discovers a problem the group cannot ignore.",
            f"What happened before still matters: {clipped(prior, 13)}",
            f"A detail noticed by {ally} connects the new evidence to {thread}.",
            "Following it removes the easiest escape and confirms the chapters are part of the same mystery.",
            f"That proof forces {lead} to reinterpret something the group believed was settled.",
            f"Then {ally} sees the cost: protecting everyone and exposing the truth now point in opposite directions.",
            f"The decision pushes {act} forward instead of resetting the story.",
            clipped(cliff, 15),
        ],
    ]
    best = None
    for lines in variants:
        script = " ".join(x for x in lines if x)
        hook = lines[0]
        candidate = {**project, "script": script, "hook": hook}
        result = creative_preflight(candidate)
        if best is None or result["score"] > best[1]["score"]:
            best = (candidate, result)
        if result["passed"]:
            return candidate, result
    return best


def apply_rewrite(series, ep_list, barrier_index, project):
    episode = ep_list[barrier_index]
    previous = ep_list[barrier_index - 1] if barrier_index else None
    candidate, result = rebuild_fiction(series, episode, project, previous)
    report(project, result["passed"], result["score"], result.get("reasons") or ["fiction continuity rewrite"], {
        "episode_number": episode["episode_number"],
        "preflight": result,
        "old_failure": project.get("failure_reason"),
    })
    if not result["passed"]:
        return False
    attempts = int(project.get("qc_attempts") or 0) + 1
    now = datetime.now(timezone.utc).isoformat()
    patch("video_projects", project["id"], {
        "script": candidate["script"],
        "hook": candidate["hook"],
        "creative_score": result["score"],
        "status": "generating",
        "output_url": None,
        "scheduled_publish_at": None,
        "failure_reason": "Series continuity script rebuilt and queued for clean rerender.",
        "qc_attempts": attempts,
        "updated_at": now,
    })
    patch("series_episodes", episode["id"], {
        "script": candidate["script"],
        "status": "generating",
        "updated_at": now,
    })
    refreshed = {**project, **candidate}
    refreshed["status"] = "generating"
    refreshed["qc_attempts"] = attempts
    set_step(refreshed, "script", "passed", "Series continuity controller rebuilt concise spoken narration while preserving the chapter handoff.")
    set_step(refreshed, "creative_preflight", "passed", f"Series continuity rewrite passed at {result['score']}/100.")
    queue(refreshed, "series-continuity-creative-repair")
    return True


def rerender(project, episode):
    attempts = int(project.get("qc_attempts") or 0) + 1
    now = datetime.now(timezone.utc).isoformat()
    detail = f"Series continuity repair attempt {attempts}: rerendering the earliest unpublished chapter first."
    patch("video_projects", project["id"], {
        "status": "generating",
        "output_url": None,
        "scheduled_publish_at": None,
        "failure_reason": detail,
        "qc_attempts": attempts,
        "updated_at": now,
    })
    patch("series_episodes", episode["id"], {"status": "generating", "updated_at": now})
    refreshed = {**project, "status": "generating", "qc_attempts": attempts}
    queued = queue(refreshed, "series-continuity-render-repair")
    report(refreshed, True, 70, [detail], {
        "episode_number": episode["episode_number"],
        "attempt": attempts,
        "queued": queued,
    })
    return queued


def cancel_later_queued(ep_list, projects, barrier_index):
    held = 0
    now = datetime.now(timezone.utc).isoformat()
    barrier_number = ep_list[barrier_index]["episode_number"]
    for episode in ep_list[barrier_index + 1:]:
        project = projects.get(episode["id"])
        if not project:
            continue
        for job in jobs(project["id"], ("queued",)):
            patch("render_jobs", job["id"], {
                "status": "failed",
                "error": f"Series continuity hold: chapter {barrier_number} must publish first.",
                "completed_at": now,
                "updated_at": now,
            })
            held += 1
    return held


summary = {
    "series_checked": 0,
    "status_synced": 0,
    "next_episode_fixed": 0,
    "later_jobs_held": 0,
    "barriers_queued": 0,
    "barriers_repaired": 0,
    "waiting": 0,
}

series_rows = request("GET", "/rest/v1/series_projects?status=eq.active&select=*&order=created_at.asc") or []
for series in series_rows:
    ep_list = episodes(series["id"])
    if not ep_list:
        continue
    summary["series_checked"] += 1
    projects = {}
    for episode in ep_list:
        project = get_project(episode.get("video_project_id"))
        if not project:
            continue
        projects[episode["id"]] = project
        expected = mapped_episode_status(project.get("status"))
        if episode.get("status") != expected:
            patch("series_episodes", episode["id"], {
                "status": expected,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            episode["status"] = expected
            summary["status_synced"] += 1

    expected_next = max(int(x["episode_number"]) for x in ep_list) + 1
    if int(series.get("next_episode_number") or 1) != expected_next:
        patch("series_projects", series["id"], {
            "next_episode_number": expected_next,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        summary["next_episode_fixed"] += 1

    barrier_index = None
    barrier_project = None
    for index, episode in enumerate(ep_list):
        project = projects.get(episode["id"])
        if not project or project.get("status") != "posted":
            barrier_index = index
            barrier_project = project
            break
    if barrier_index is None:
        continue

    summary["later_jobs_held"] += cancel_later_queued(ep_list, projects, barrier_index)
    if not barrier_project:
        summary["waiting"] += 1
        continue

    episode = ep_list[barrier_index]
    attempts = int(barrier_project.get("qc_attempts") or 0)
    status = barrier_project.get("status")
    if attempts >= 5 and status == "failed":
        report(barrier_project, False, 0, ["series continuity automatic repair limit reached"], {
            "episode_number": episode["episode_number"],
            "attempts": attempts,
            "failure": barrier_project.get("failure_reason"),
        })
        summary["waiting"] += 1
        continue

    if status == "generating":
        result = creative_preflight(barrier_project)
        if result["passed"]:
            if queue(barrier_project, "series-continuity"):
                summary["barriers_queued"] += 1
        elif factual(series, barrier_project):
            report(barrier_project, False, result["score"], ["factual series chapter needs a verified-source rewrite before rendering"], {"preflight": result})
            summary["waiting"] += 1
        elif apply_rewrite(series, ep_list, barrier_index, barrier_project):
            summary["barriers_repaired"] += 1
        else:
            summary["waiting"] += 1
        continue

    if status == "failed":
        if factual(series, barrier_project) and has_creative_failure(barrier_project):
            report(barrier_project, False, 20, ["factual series chapter needs verified evidence before creative repair"], {
                "episode_number": episode["episode_number"],
                "failure": barrier_project.get("failure_reason"),
            })
            summary["waiting"] += 1
        elif not factual(series, barrier_project) and has_creative_failure(barrier_project):
            if apply_rewrite(series, ep_list, barrier_index, barrier_project):
                summary["barriers_repaired"] += 1
            else:
                summary["waiting"] += 1
        elif has_mechanical_failure(barrier_project):
            if rerender(barrier_project, episode):
                summary["barriers_repaired"] += 1
        else:
            report(barrier_project, False, 30, ["series barrier is not safely auto-repairable"], {
                "episode_number": episode["episode_number"],
                "failure": barrier_project.get("failure_reason"),
            })
            summary["waiting"] += 1
        continue

    if status not in ("quality_check", "ready", "scheduled", "publishing"):
        summary["waiting"] += 1

print(json.dumps(summary))
