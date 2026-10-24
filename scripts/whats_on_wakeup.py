#!/usr/bin/env python3
"""Recover a missed What's On daily refresh without duplicating a healthy run."""
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SGT = timezone(timedelta(hours=8))
WORKFLOW = "whats-on-weekly.yml"  # Keep the existing filename for the admin button.
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}

def latest_window(now):
    local = now.astimezone(SGT)
    target = local.replace(hour=4, minute=15, second=0, microsecond=0)
    if local < target:
        target -= timedelta(days=1)
    return target

def parse_time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else None
    except (ValueError, TypeError):
        return None

def feed_fresh(feed, target, now):
    if not isinstance(feed, dict) or not isinstance(feed.get("events"), list):
        return False
    updated = parse_time(feed.get("updated_at"))
    return bool(updated and target <= updated <= now + timedelta(minutes=5)
                and not feed.get("all_sources_failed", False))

def recovery_decision(feed, runs, target, now):
    # An active main job will do the work, even if it was queued before the target.
    for run in runs:
        if run.get("head_branch") == "main" and run.get("status") in ACTIVE:
            created = parse_time(run.get("created_at"))
            stuck_queue = (run.get("status") != "in_progress" and created
                           and now - created >= timedelta(minutes=30))
            if not stuck_queue:
                return "active"
    # Source-specific blocks do not cause repeated full-site refreshes.
    if feed_fresh(feed, target, now):
        return "fresh"
    return "dispatch"

class GitHub:
    def __init__(self, repository, token):
        self.base = "https://api.github.com/repos/" + repository
        self.token = token

    def request(self, path, payload=None):
        request = Request(self.base + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Accept": "application/vnd.github+json",
                     "Authorization": "Bearer " + self.token,
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json"},
            method="GET" if payload is None else "POST")
        with urlopen(request, timeout=30) as response:
            content = response.read()
            return json.loads(content) if content else None

    def feed(self):
        file = self.request("/contents/events.json?ref=main")
        return json.loads(base64.b64decode(file["content"]))

def main():
    now = datetime.now(timezone.utc)
    target = latest_window(now)
    client = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    # If either read fails, fail visibly rather than guessing and launching duplicates.
    feed = client.feed()
    runs = client.request("/actions/workflows/" + WORKFLOW + "/runs?branch=main&per_page=50")["workflow_runs"]
    decision = recovery_decision(feed, runs, target, now)
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if decision == "dispatch" and not dry_run:
        client.request("/actions/workflows/" + WORKFLOW + "/dispatches", {"ref": "main", "inputs": {"recoveryTarget": target.isoformat()}})
        message = "Missing or unsuccessful daily feed: recovery dispatch accepted."
    elif decision == "dispatch":
        message = "Dry run: a recovery refresh would be launched."
    elif decision == "active":
        message = "A refresh is already queued or running; no duplicate launched."
    else:
        message = "Today's feed is fresh; no recovery needed."
    print(f"Daily target: {target.isoformat()}")
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"Daily target: {target.isoformat()}\n\n{message}\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
