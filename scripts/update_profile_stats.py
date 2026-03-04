#!/usr/bin/env python3
"""Update README commit goal and streak stats for the current year."""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

START_TAG = "<!--START_STATS-->"
END_TAG = "<!--END_STATS-->"


def github_graphql(query: str, variables: dict[str, str], token: str) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-readme-updater",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}: {details}") from exc

    if "errors" in body:
        raise RuntimeError(f"GraphQL error: {body['errors']}")

    return body["data"]


def to_date(date_string: str) -> dt.date:
    return dt.datetime.strptime(date_string, "%Y-%m-%d").date()


def calculate_streak(days: list[tuple[dt.date, int]], today: dt.date) -> tuple[int, int]:
    if not days:
        return 0, 0

    day_map = {day: count for day, count in days}

    best = 0
    running = 0
    for day, count in sorted(days, key=lambda item: item[0]):
        if count > 0:
            running += 1
            best = max(best, running)
        else:
            running = 0

    cursor = today
    if day_map.get(today, 0) == 0:
        cursor = today - dt.timedelta(days=1)

    current = 0
    while day_map.get(cursor, 0) > 0:
        current += 1
        cursor -= dt.timedelta(days=1)

    return current, best


def make_progress_bar(progress: float, width: int = 30) -> str:
    filled = int(round(width * progress))
    filled = max(0, min(width, filled))
    return f"{'#' * filled}{'-' * (width - filled)}"


def build_stats_block(year: int, commits: int, goal: int, current_streak: int, best_streak: int) -> str:
    progress = min(commits / goal, 1.0) if goal > 0 else 0.0
    remaining = max(goal - commits, 0)
    pct = progress * 100
    bar = make_progress_bar(progress)

    return (
        f"{START_TAG}\n"
        f"- Year: **{year}**\n"
        f"- Current commits: **{commits}**\n"
        f"- Goal: **{goal}**\n"
        f"- Remaining: **{remaining}**\n"
        f"- Current streak: **{current_streak} days**\n"
        f"- Best streak this year: **{best_streak} days**\n"
        f"- Progress: `{bar}` **{pct:.1f}%**\n"
        f"{END_TAG}"
    )


def update_readme(readme_path: pathlib.Path, replacement_block: str) -> None:
    readme_text = readme_path.read_text(encoding="utf-8")

    pattern = re.compile(
        rf"{re.escape(START_TAG)}.*?{re.escape(END_TAG)}",
        flags=re.DOTALL,
    )

    if not pattern.search(readme_text):
        raise RuntimeError(f"Could not find stats markers in {readme_path}")

    updated = pattern.sub(replacement_block, readme_text)

    if updated != readme_text:
        readme_path.write_text(updated, encoding="utf-8")
        print(f"Updated {readme_path}")
    else:
        print("README already up to date")


def main() -> int:
    username = os.getenv("GITHUB_USERNAME", "Hanbrar")
    token = os.getenv("GITHUB_TOKEN", "")
    goal = int(os.getenv("COMMIT_GOAL", "500"))

    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1

    now_utc = dt.datetime.now(dt.timezone.utc)
    year = now_utc.year
    start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)

    query = """
    query($username: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $username) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    variables = {
        "username": username,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": now_utc.isoformat().replace("+00:00", "Z"),
    }

    data = github_graphql(query=query, variables=variables, token=token)
    user = data.get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")

    collection = user["contributionsCollection"]
    # Match GitHub profile's yearly headline count (includes restricted/private
    # contributions when the token and profile settings allow it).
    commits = int(
        collection["contributionCalendar"].get(
            "totalContributions", collection["totalCommitContributions"]
        )
    )

    days: list[tuple[dt.date, int]] = []
    for week in collection["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            day_date = to_date(day["date"])
            if day_date.year == year:
                days.append((day_date, int(day["contributionCount"])))

    today = now_utc.date()
    current_streak, best_streak = calculate_streak(days=days, today=today)

    stats_block = build_stats_block(
        year=year,
        commits=commits,
        goal=goal,
        current_streak=current_streak,
        best_streak=best_streak,
    )

    repo_root = pathlib.Path(__file__).resolve().parent.parent
    readme_path = repo_root / "README.md"
    update_readme(readme_path=readme_path, replacement_block=stats_block)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

