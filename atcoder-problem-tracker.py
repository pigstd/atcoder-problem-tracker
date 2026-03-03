#!/usr/bin/env python3

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_BASE = "https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"
API_PROXY_PREFIX = "https://r.jina.ai/http://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"
MAX_CONSECUTIVE_FAILURES = 5
CACHE_DIR = Path("cache/users")
CACHE_VERSION = 1
CACHE_MIN_UPDATE_INTERVAL_SECONDS = 86400
DIRECT_API_BLOCKED = False


class TrackerError(Exception):
    """Domain-specific error for this script."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether users in a group have submissions in a target contest."
    )
    parser.add_argument(
        "-c",
        "--contest",
        required=True,
        help="Contest ID to check, for example: abc403",
    )
    parser.add_argument(
        "-g",
        "--group",
        required=True,
        help="Group file name in usergroup/ without .json suffix, for example: example",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Force rebuild user cache from from_second=0, ignoring update interval.",
    )
    return parser.parse_args()


def load_group_users(group_name: str) -> list[str]:
    group_file = Path("usergroup") / f"{group_name}.json"
    if not group_file.exists():
        raise TrackerError(f"group file not found: {group_file}")

    try:
        with group_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise TrackerError(f"invalid JSON in group file {group_file}: {exc}") from exc
    except OSError as exc:
        raise TrackerError(f"cannot read group file {group_file}: {exc}") from exc

    if not isinstance(data, dict):
        raise TrackerError(f"invalid group format in {group_file}: root must be an object")

    users = data.get("users")
    if users is None:
        raise TrackerError(f"invalid group format in {group_file}: missing 'users' field")
    if not isinstance(users, list):
        raise TrackerError(f"invalid group format in {group_file}: 'users' must be a list")
    if not users:
        raise TrackerError(f"invalid group format in {group_file}: 'users' must not be empty")
    if not all(isinstance(user, str) and user.strip() for user in users):
        raise TrackerError(
            f"invalid group format in {group_file}: every user must be a non-empty string"
        )

    return users


def fetch_submissions_with_retry(user_id: str, from_second: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"user": user_id, "from_second": str(from_second)})
    direct_url = f"{API_BASE}?{params}"
    proxy_url = f"{API_PROXY_PREFIX}?{params}"

    consecutive_failures = 0
    last_error: str | None = None
    while consecutive_failures < MAX_CONSECUTIVE_FAILURES:
        try:
            result = _fetch_submissions_once(direct_url, proxy_url)
            if not isinstance(result, list):
                raise TrackerError(
                    f"unexpected API response for user {user_id} from_second={from_second}: "
                    "response is not a list"
                )

            return result
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
            TrackerError,
        ) as exc:
            consecutive_failures += 1
            last_error = str(exc)

    raise TrackerError(
        f"API request failed 5 times consecutively for user {user_id}, "
        f"from_second={from_second}: {last_error}"
    )


def _fetch_submissions_once(direct_url: str, proxy_url: str) -> list[dict[str, Any]]:
    global DIRECT_API_BLOCKED

    headers = {"User-Agent": "atcoder-problem-tracker/1.0 (+https://github.com/)"}

    # 首先尝试直连 API；如果直连 403，则自动尝试只读代理回退。
    if not DIRECT_API_BLOCKED:
        direct_request = urllib.request.Request(direct_url, headers=headers)
        try:
            with urllib.request.urlopen(direct_request, timeout=30) as resp:
                payload = resp.read()
            time.sleep(1)
            return _parse_submissions_payload(payload.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            time.sleep(1)
            if exc.code != 403:
                raise
            DIRECT_API_BLOCKED = True

    proxy_request = urllib.request.Request(proxy_url, headers=headers)
    with urllib.request.urlopen(proxy_request, timeout=30) as resp:
        payload = resp.read()
    time.sleep(1)
    return _parse_submissions_payload(payload.decode("utf-8"))


def _parse_submissions_payload(text: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        marker = "Markdown Content:"
        if marker not in text:
            raise
        _, markdown = text.split(marker, maxsplit=1)
        parsed = json.loads(markdown.strip())

    if not isinstance(parsed, list):
        raise TrackerError("API response is not a submission list")
    return parsed


def ensure_cache_dir_exists() -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TrackerError(f"cannot create cache directory {CACHE_DIR}: {exc}") from exc


def get_cache_file_path(user_id: str) -> Path:
    return CACHE_DIR / f"{user_id}.json"


def _now_utc_iso8601() -> str:
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def _parse_utc_iso8601_to_epoch(value: str) -> float:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError("timezone info is required")
    return dt.timestamp()


def _validate_user_cache(cache_data: Any, user_id: str, cache_file: Path) -> dict[str, Any]:
    if not isinstance(cache_data, dict):
        raise TrackerError(f"invalid cache format in {cache_file}: root must be an object")

    version = cache_data.get("version")
    if not isinstance(version, int):
        raise TrackerError(f"invalid cache format in {cache_file}: 'version' must be an integer")
    if version != CACHE_VERSION:
        raise TrackerError(
            f"unsupported cache version in {cache_file}: expected {CACHE_VERSION}, got {version}"
        )

    cached_user_id = cache_data.get("user_id")
    if not isinstance(cached_user_id, str) or not cached_user_id:
        raise TrackerError(f"invalid cache format in {cache_file}: 'user_id' must be a string")
    if cached_user_id != user_id:
        raise TrackerError(
            f"invalid cache format in {cache_file}: user_id mismatch "
            f"(expected {user_id}, got {cached_user_id})"
        )

    last_updated_at = cache_data.get("last_updated_at")
    if not isinstance(last_updated_at, str) or not last_updated_at:
        raise TrackerError(
            f"invalid cache format in {cache_file}: 'last_updated_at' must be a non-empty string"
        )
    try:
        _parse_utc_iso8601_to_epoch(last_updated_at)
    except ValueError as exc:
        raise TrackerError(
            f"invalid cache format in {cache_file}: invalid 'last_updated_at': {last_updated_at}"
        ) from exc

    next_from_second = cache_data.get("next_from_second")
    if not isinstance(next_from_second, int) or next_from_second < 0:
        raise TrackerError(
            f"invalid cache format in {cache_file}: 'next_from_second' must be a non-negative integer"
        )

    submissions = cache_data.get("submissions")
    if not isinstance(submissions, list):
        raise TrackerError(f"invalid cache format in {cache_file}: 'submissions' must be a list")

    return cache_data


def load_user_cache(user_id: str) -> dict[str, Any] | None:
    cache_file = get_cache_file_path(user_id)
    if not cache_file.exists():
        return None

    try:
        with cache_file.open("r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except json.JSONDecodeError as exc:
        raise TrackerError(f"invalid JSON in cache file {cache_file}: {exc}") from exc
    except OSError as exc:
        raise TrackerError(f"cannot read cache file {cache_file}: {exc}") from exc

    return _validate_user_cache(cache_data, user_id, cache_file)


def write_user_cache(user_id: str, cache_data: dict[str, Any]) -> None:
    cache_file = get_cache_file_path(user_id)
    tmp_file = cache_file.with_suffix(f"{cache_file.suffix}.tmp")

    try:
        with tmp_file.open("w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, cache_file)
    except OSError as exc:
        raise TrackerError(f"cannot write cache file {cache_file}: {exc}") from exc
    finally:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass


def _collect_submission_ids(submissions: list[Any]) -> set[int]:
    known_ids: set[int] = set()
    for submission in submissions:
        if not isinstance(submission, dict):
            continue
        submission_id = submission.get("id")
        if isinstance(submission_id, int):
            known_ids.add(submission_id)
    return known_ids


def _should_skip_cache_update(last_updated_at: str, now_epoch_second: float | None = None) -> bool:
    if now_epoch_second is None:
        now_epoch_second = time.time()
    updated_at_epoch = _parse_utc_iso8601_to_epoch(last_updated_at)
    return now_epoch_second - updated_at_epoch < CACHE_MIN_UPDATE_INTERVAL_SECONDS


def _fetch_and_merge_submissions(
    user_id: str,
    initial_from_second: int,
    merged_submissions: list[Any],
    known_submission_ids: set[int],
) -> int:
    from_second = initial_from_second

    while True:
        submissions = fetch_submissions_with_retry(user_id, from_second)
        if not submissions:
            return from_second

        for submission in submissions:
            if not isinstance(submission, dict):
                continue
            submission_id = submission.get("id")
            if isinstance(submission_id, int):
                if submission_id in known_submission_ids:
                    continue
                known_submission_ids.add(submission_id)
            merged_submissions.append(submission)

        epoch_seconds = [
            s.get("epoch_second")
            for s in submissions
            if isinstance(s, dict) and isinstance(s.get("epoch_second"), int)
        ]
        if not epoch_seconds:
            raise TrackerError(
                f"unexpected API response for user {user_id}: no valid epoch_second field found"
            )
        from_second = max(epoch_seconds) + 1


def update_user_cache(user_id: str, refresh_cache: bool) -> dict[str, Any]:
    existing_cache = load_user_cache(user_id)

    should_full_rebuild = refresh_cache or existing_cache is None
    if should_full_rebuild:
        print(f"updating cache for {user_id} ...", flush=True)
        merged_submissions: list[Any] = []
        known_submission_ids: set[int] = set()
        next_from_second = _fetch_and_merge_submissions(
            user_id=user_id,
            initial_from_second=0,
            merged_submissions=merged_submissions,
            known_submission_ids=known_submission_ids,
        )
    else:
        assert existing_cache is not None
        last_updated_at = existing_cache["last_updated_at"]
        if _should_skip_cache_update(last_updated_at):
            print(f"cache hit, skip update for {user_id}", flush=True)
            return existing_cache

        print(f"updating cache for {user_id} ...", flush=True)
        merged_submissions = list(existing_cache["submissions"])
        known_submission_ids = _collect_submission_ids(merged_submissions)
        next_from_second = _fetch_and_merge_submissions(
            user_id=user_id,
            initial_from_second=existing_cache["next_from_second"],
            merged_submissions=merged_submissions,
            known_submission_ids=known_submission_ids,
        )

    updated_cache = {
        "version": CACHE_VERSION,
        "user_id": user_id,
        "last_updated_at": _now_utc_iso8601(),
        "next_from_second": next_from_second,
        "submissions": merged_submissions,
    }
    write_user_cache(user_id, updated_cache)
    return updated_cache


def cache_has_done_contest(submissions: list[Any], target_contest: str) -> bool:
    target_lower = target_contest.lower()
    for submission in submissions:
        if (
            isinstance(submission, dict)
            and isinstance(submission.get("contest_id"), str)
            and submission["contest_id"].lower() == target_lower
        ):
            return True
    return False


def main() -> int:
    args = parse_args()
    users = load_group_users(args.group)
    ensure_cache_dir_exists()

    user_caches: dict[str, dict[str, Any]] = {}
    for user_id in users:
        print(f"checking user {user_id} ...", flush=True)
        user_caches[user_id] = update_user_cache(user_id, args.refresh_cache)

    found_any = False
    for user_id in users:
        if cache_has_done_contest(user_caches[user_id]["submissions"], args.contest):
            print(f"{user_id} done {args.contest}")
            found_any = True

    if not found_any:
        print(f"no users have done {args.contest}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
