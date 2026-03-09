from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.core.cache import collect_submission_ids
from src.core.errors import TrackerError
from src.oj.base import ContestKey, OJAdapter


API_BASE = "https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"
API_PROXY_PREFIX = "https://r.jina.ai/http://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"
MAX_CONSECUTIVE_FAILURES = 5
REQUEST_INTERVAL_SECONDS = 1
USER_AGENT = "oj-problem-tracker/1.0 (+https://github.com/)"


class AtCoderAdapter(OJAdapter):
    """Adapter for AtCoder submission fetching, caching, and contest matching."""
    name = "atcoder"

    def __init__(self) -> None:
        """Track whether the direct API should be bypassed in favor of the proxy."""
        self._direct_api_blocked = False

    def validate_contest(self, contest: str) -> ContestKey:
        """Return the AtCoder contest ID unchanged."""
        return contest

    def validate_cache_fields(self, cache_data: dict[str, Any], cache_file: Path) -> None:
        """Ensure AtCoder caches store a valid incremental pagination cursor."""
        next_from_second = cache_data.get("next_from_second")
        if not isinstance(next_from_second, int) or next_from_second < 0:
            raise TrackerError(
                f"invalid cache format in {cache_file}: "
                "'next_from_second' must be a non-negative integer"
            )

    def update_submissions(
        self,
        user_id: str,
        existing_cache: dict[str, Any] | None,
        refresh_cache: bool,
    ) -> dict[str, Any]:
        """Fetch new AtCoder submissions and merge them into the stored cache payload."""
        should_full_rebuild = refresh_cache or existing_cache is None

        if should_full_rebuild:
            merged_submissions: list[Any] = []
            known_submission_ids: set[int] = set()
            initial_from_second = 0
        else:
            assert existing_cache is not None
            merged_submissions = list(existing_cache["submissions"])
            known_submission_ids = collect_submission_ids(merged_submissions)
            initial_from_second = existing_cache["next_from_second"]

        next_from_second = self._fetch_incremental(
            user_id=user_id,
            initial_from_second=initial_from_second,
            merged_submissions=merged_submissions,
            known_submission_ids=known_submission_ids,
        )

        return {
            "submissions": merged_submissions,
            "next_from_second": next_from_second,
        }

    def submission_matches_contest(self, submission: Any, contest: ContestKey) -> bool:
        """Return whether a submission belongs to the requested AtCoder contest."""
        if not isinstance(contest, str):
            raise TrackerError("internal error: atcoder target contest must be string")

        return (
            isinstance(submission, dict)
            and isinstance(submission.get("contest_id"), str)
            and submission["contest_id"].lower() == contest.lower()
        )

    def _fetch_incremental(
        self,
        user_id: str,
        initial_from_second: int,
        merged_submissions: list[Any],
        known_submission_ids: set[int],
    ) -> int:
        """Incrementally fetch pages until exhaustion and return the next cursor."""
        from_second = initial_from_second

        while True:
            submissions = self._fetch_submissions_with_retry(user_id, from_second)
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

            from_second = self._extract_next_from_second(user_id, submissions)

    def _fetch_submissions_with_retry(self, user_id: str, from_second: int) -> list[dict[str, Any]]:
        """Retry a paged AtCoder request until success or the failure limit is reached."""
        consecutive_failures = 0
        last_error: str | None = None

        while consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            try:
                result = self._fetch_submissions_once(user_id, from_second)
                if not isinstance(result, list):
                    raise TrackerError(
                        f"unexpected AtCoder response for user {user_id} from_second={from_second}: "
                        "response is not a list"
                    )
                return result
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
                json.JSONDecodeError,
                ValueError,
                TrackerError,
            ) as exc:
                consecutive_failures += 1
                last_error = str(exc)

        raise TrackerError(
            f"AtCoder API request failed {MAX_CONSECUTIVE_FAILURES} times consecutively for "
            f"user {user_id}, from_second={from_second}: {last_error}"
        )

    def _fetch_submissions_once(self, user_id: str, from_second: int) -> list[dict[str, Any]]:
        """Fetch one AtCoder page, falling back to the proxy after a 403 response."""
        params = urllib.parse.urlencode({"user": user_id, "from_second": str(from_second)})
        direct_url = f"{API_BASE}?{params}"
        proxy_url = f"{API_PROXY_PREFIX}?{params}"
        headers = {"User-Agent": USER_AGENT}

        if not self._direct_api_blocked:
            direct_request = urllib.request.Request(direct_url, headers=headers)
            try:
                with urllib.request.urlopen(direct_request, timeout=30) as resp:
                    payload = resp.read()
                time.sleep(REQUEST_INTERVAL_SECONDS)
                return self._parse_submissions_payload(payload.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                time.sleep(REQUEST_INTERVAL_SECONDS)
                if exc.code != 403:
                    raise
                self._direct_api_blocked = True

        proxy_request = urllib.request.Request(proxy_url, headers=headers)
        with urllib.request.urlopen(proxy_request, timeout=30) as resp:
            payload = resp.read()
        time.sleep(REQUEST_INTERVAL_SECONDS)
        return self._parse_submissions_payload(payload.decode("utf-8"))

    @staticmethod
    def _parse_submissions_payload(text: str) -> list[dict[str, Any]]:
        """Parse either raw JSON or proxy-wrapped Markdown into a submission list."""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            marker = "Markdown Content:"
            if marker not in text:
                raise
            _, markdown = text.split(marker, maxsplit=1)
            parsed = json.loads(markdown.strip())

        if not isinstance(parsed, list):
            raise ValueError("AtCoder API response is not a submission list")
        return parsed

    @staticmethod
    def _extract_next_from_second(user_id: str, submissions: list[dict[str, Any]]) -> int:
        """Compute the next incremental cursor from the newest fetched submission."""
        epoch_seconds = [
            submission.get("epoch_second")
            for submission in submissions
            if isinstance(submission, dict) and isinstance(submission.get("epoch_second"), int)
        ]
        if not epoch_seconds:
            raise TrackerError(
                f"unexpected AtCoder response for user {user_id}: "
                "no valid epoch_second field found"
            )
        return max(epoch_seconds) + 1
