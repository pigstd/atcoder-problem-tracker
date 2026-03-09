from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.core.errors import TrackerError
from src.oj.base import ContestKey, OJAdapter


API_BASE = "https://codeforces.com/api/user.status"
MAX_CONSECUTIVE_FAILURES = 5
REQUEST_INTERVAL_SECONDS = 2
PAGE_SIZE = 1000
USER_AGENT = "oj-problem-tracker/1.0 (+https://github.com/)"


class CodeforcesAdapter(OJAdapter):
    """Adapter for Codeforces submission fetching, caching, and contest matching."""
    name = "cf"

    def validate_contest(self, contest: str) -> ContestKey:
        """Validate that a Codeforces contest ID is numeric and normalize it to int."""
        if not contest.isdigit():
            raise TrackerError("for --oj cf, --contest must be a pure numeric contestId")
        return int(contest)

    def validate_cache_fields(self, cache_data: dict[str, Any], cache_file: Path) -> None:
        """Accept current Codeforces caches and guard legacy next_from_second values if present."""
        if "next_from_second" not in cache_data:
            return

        next_from_second = cache_data["next_from_second"]
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
        """Rebuild the Codeforces submission payload from a fresh full fetch."""
        del existing_cache
        del refresh_cache
        return {"submissions": self._fetch_full_submissions(user_id)}

    def submission_matches_contest(self, submission: Any, contest: ContestKey) -> bool:
        """Return whether a submission belongs to the requested Codeforces contest."""
        if not isinstance(contest, int):
            raise TrackerError("internal error: cf target contest must be int")

        return (
            isinstance(submission, dict)
            and isinstance(submission.get("contestId"), int)
            and submission["contestId"] == contest
        )

    def _fetch_full_submissions(self, handle: str) -> list[Any]:
        """Fetch every submission page for a handle and deduplicate by submission ID."""
        all_submissions: list[Any] = []
        known_submission_ids: set[int] = set()
        from_index = 1

        while True:
            submissions = self._fetch_status_page_with_retry(handle, from_index, PAGE_SIZE)
            if not submissions:
                break

            for submission in submissions:
                if not isinstance(submission, dict):
                    continue
                submission_id = submission.get("id")
                if isinstance(submission_id, int):
                    if submission_id in known_submission_ids:
                        continue
                    known_submission_ids.add(submission_id)
                all_submissions.append(submission)

            if len(submissions) < PAGE_SIZE:
                break

            from_index += PAGE_SIZE

        return all_submissions

    def _fetch_status_page_with_retry(
        self,
        handle: str,
        from_index: int,
        count: int,
    ) -> list[dict[str, Any]]:
        """Retry a paged Codeforces request until success or the failure limit is reached."""
        consecutive_failures = 0
        last_error: str | None = None

        while consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            try:
                result = self._fetch_status_page_once(handle, from_index, count)
                if not isinstance(result, list):
                    raise TrackerError(
                        f"unexpected Codeforces response for handle {handle} from={from_index}: "
                        "result is not a list"
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
            f"Codeforces API request failed {MAX_CONSECUTIVE_FAILURES} times consecutively for "
            f"handle {handle}, from={from_index}, count={count}: {last_error}"
        )

    def _fetch_status_page_once(self, handle: str, from_index: int, count: int) -> list[dict[str, Any]]:
        """Fetch and validate a single Codeforces status page."""
        params = urllib.parse.urlencode(
            {
                "handle": handle,
                "from": str(from_index),
                "count": str(count),
            }
        )
        url = f"{API_BASE}?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        with urllib.request.urlopen(request, timeout=30) as resp:
            payload = resp.read()
        time.sleep(REQUEST_INTERVAL_SECONDS)

        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("Codeforces API response root is not an object")

        status = parsed.get("status")
        if status != "OK":
            comment = parsed.get("comment")
            raise ValueError(f"Codeforces API status is not OK: status={status}, comment={comment}")

        result = parsed.get("result")
        if not isinstance(result, list):
            raise ValueError("Codeforces API result is not a submission list")

        return result
