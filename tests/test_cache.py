import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.cli import ANSI_GREEN, ANSI_RED, ANSI_RESET, load_group_users, main, run
from src.core import cache as cache_store
from src.core import tracker as tracker_service
from src.core.errors import TrackerError
from src.oj.atcoder import AtCoderAdapter
from src.oj.cf import CodeforcesAdapter


def _iso_utc_hours_ago(hours: int) -> str:
    timestamp = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    return timestamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _cache_payload(
    oj: str,
    user_id: str,
    last_updated_at: str,
    submissions: list[dict],
    next_from_second: int | None = None,
):
    payload = {
        "version": cache_store.CACHE_VERSION,
        "oj": oj,
        "user_id": user_id,
        "last_updated_at": last_updated_at,
        "submissions": submissions,
    }
    if oj == "atcoder":
        payload["next_from_second"] = 0 if next_from_second is None else next_from_second
    return payload


class CacheBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_cache_root = cache_store.CACHE_ROOT
        cache_store.CACHE_ROOT = Path(self.tmpdir.name) / "cache"

        self.atcoder = AtCoderAdapter()
        self.cf = CodeforcesAdapter()

        cache_store.ensure_cache_dir_exists("atcoder")
        cache_store.ensure_cache_dir_exists("cf")

    def tearDown(self) -> None:
        cache_store.CACHE_ROOT = self.original_cache_root
        self.tmpdir.cleanup()

    def test_atcoder_create_cache_for_new_user(self) -> None:
        def fake_fetch(user_id: str, from_second: int):
            self.assertEqual(user_id, "alice")
            if from_second == 0:
                return [{"id": 1, "epoch_second": 100, "contest_id": "abc100"}]
            if from_second == 101:
                return []
            self.fail(f"unexpected from_second={from_second}")

        self.atcoder._fetch_submissions_with_retry = fake_fetch
        cache = tracker_service.update_user_cache(self.atcoder, "alice", refresh_cache=False)

        self.assertEqual(cache["next_from_second"], 101)
        self.assertEqual(len(cache["submissions"]), 1)
        self.assertTrue(cache_store.get_cache_file_path("atcoder", "alice").exists())

    def test_atcoder_skip_update_within_interval(self) -> None:
        payload = _cache_payload(
            oj="atcoder",
            user_id="bob",
            last_updated_at=_iso_utc_hours_ago(1),
            next_from_second=42,
            submissions=[{"id": 11, "epoch_second": 41, "contest_id": "abc001"}],
        )
        cache_store.write_user_cache("atcoder", "bob", payload)

        called = {"value": False}

        def fake_fetch(_: str, __: int):
            called["value"] = True
            return []

        self.atcoder._fetch_submissions_with_retry = fake_fetch
        cache = tracker_service.update_user_cache(self.atcoder, "bob", refresh_cache=False)

        self.assertFalse(called["value"])
        self.assertEqual(cache["next_from_second"], 42)
        self.assertEqual(len(cache["submissions"]), 1)

    def test_atcoder_incremental_update_and_dedup(self) -> None:
        payload = _cache_payload(
            oj="atcoder",
            user_id="carol",
            last_updated_at=_iso_utc_hours_ago(48),
            next_from_second=10,
            submissions=[{"id": 1, "epoch_second": 9, "contest_id": "abc001"}],
        )
        cache_store.write_user_cache("atcoder", "carol", payload)

        def fake_fetch(user_id: str, from_second: int):
            self.assertEqual(user_id, "carol")
            if from_second == 10:
                return [
                    {"id": 1, "epoch_second": 10, "contest_id": "abc001"},
                    {"id": 2, "epoch_second": 12, "contest_id": "abc002"},
                ]
            if from_second == 13:
                return []
            self.fail(f"unexpected from_second={from_second}")

        self.atcoder._fetch_submissions_with_retry = fake_fetch
        cache = tracker_service.update_user_cache(self.atcoder, "carol", refresh_cache=False)

        self.assertEqual(cache["next_from_second"], 13)
        self.assertEqual([s["id"] for s in cache["submissions"]], [1, 2])

    def test_atcoder_refresh_cache_rebuilds_from_zero(self) -> None:
        payload = _cache_payload(
            oj="atcoder",
            user_id="dave",
            last_updated_at=_iso_utc_hours_ago(1),
            next_from_second=20,
            submissions=[{"id": 9, "epoch_second": 19, "contest_id": "abc001"}],
        )
        cache_store.write_user_cache("atcoder", "dave", payload)

        def fake_fetch(user_id: str, from_second: int):
            self.assertEqual(user_id, "dave")
            if from_second == 0:
                return [{"id": 101, "epoch_second": 7, "contest_id": "abc777"}]
            if from_second == 8:
                return []
            self.fail(f"unexpected from_second={from_second}")

        self.atcoder._fetch_submissions_with_retry = fake_fetch
        cache = tracker_service.update_user_cache(self.atcoder, "dave", refresh_cache=True)

        self.assertEqual(cache["next_from_second"], 8)
        self.assertEqual([s["id"] for s in cache["submissions"]], [101])

    def test_cf_create_cache_for_new_user(self) -> None:
        calls: list[tuple[int, int]] = []

        def fake_fetch(handle: str, from_index: int, count: int):
            self.assertEqual(handle, "tourist")
            calls.append((from_index, count))
            if from_index == 1:
                return [{"id": 11, "contestId": 2065, "creationTimeSeconds": 1700000000}]
            self.fail(f"unexpected from={from_index}")

        self.cf._fetch_status_page_with_retry = fake_fetch
        cache = tracker_service.update_user_cache(self.cf, "tourist", refresh_cache=False)

        self.assertEqual(calls, [(1, 1000)])
        self.assertEqual([s["id"] for s in cache["submissions"]], [11])
        self.assertNotIn("next_from_second", cache)
        self.assertTrue(cache_store.get_cache_file_path("cf", "tourist").exists())

    def test_cf_skip_update_within_interval(self) -> None:
        payload = _cache_payload(
            oj="cf",
            user_id="petr",
            last_updated_at=_iso_utc_hours_ago(1),
            submissions=[{"id": 9, "contestId": 1000, "creationTimeSeconds": 10}],
        )
        cache_store.write_user_cache("cf", "petr", payload)

        called = {"value": False}

        def fake_fetch(_: str, __: int, ___: int):
            called["value"] = True
            return []

        self.cf._fetch_status_page_with_retry = fake_fetch
        cache = tracker_service.update_user_cache(self.cf, "petr", refresh_cache=False)

        self.assertFalse(called["value"])
        self.assertEqual([s["id"] for s in cache["submissions"]], [9])

    def test_cf_stale_cache_full_refetch(self) -> None:
        payload = _cache_payload(
            oj="cf",
            user_id="neal",
            last_updated_at=_iso_utc_hours_ago(48),
            submissions=[{"id": 1, "contestId": 1000, "creationTimeSeconds": 10}],
        )
        cache_store.write_user_cache("cf", "neal", payload)

        def fake_fetch(handle: str, from_index: int, count: int):
            self.assertEqual(handle, "neal")
            self.assertEqual((from_index, count), (1, 1000))
            return [{"id": 2, "contestId": 2065, "creationTimeSeconds": 20}]

        self.cf._fetch_status_page_with_retry = fake_fetch
        cache = tracker_service.update_user_cache(self.cf, "neal", refresh_cache=False)

        self.assertEqual([s["id"] for s in cache["submissions"]], [2])

    def test_cf_refresh_cache_forces_refetch(self) -> None:
        payload = _cache_payload(
            oj="cf",
            user_id="benq",
            last_updated_at=_iso_utc_hours_ago(1),
            submissions=[{"id": 10, "contestId": 1000, "creationTimeSeconds": 10}],
        )
        cache_store.write_user_cache("cf", "benq", payload)

        called = {"value": 0}

        def fake_fetch(handle: str, from_index: int, count: int):
            self.assertEqual(handle, "benq")
            called["value"] += 1
            self.assertEqual((from_index, count), (1, 1000))
            return [{"id": 99, "contestId": 3000, "creationTimeSeconds": 999}]

        self.cf._fetch_status_page_with_retry = fake_fetch
        cache = tracker_service.update_user_cache(self.cf, "benq", refresh_cache=True)

        self.assertEqual(called["value"], 1)
        self.assertEqual([s["id"] for s in cache["submissions"]], [99])


class InputValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_cwd = Path.cwd()
        os.chdir(self.tmpdir.name)
        Path("usergroup").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.tmpdir.cleanup()

    def test_load_group_users_new_format(self) -> None:
        group_file = Path("usergroup") / "example.json"
        group_file.write_text(
            json.dumps({"atcoder": ["alice"], "cf": ["tourist", "Petr"]}),
            encoding="utf-8",
        )

        at_users = load_group_users("example", "atcoder")
        cf_users = load_group_users("example", "cf")

        self.assertEqual(at_users, ["alice"])
        self.assertEqual(cf_users, ["tourist", "Petr"])

    def test_load_group_users_rejects_old_users_field(self) -> None:
        group_file = Path("usergroup") / "legacy.json"
        group_file.write_text(json.dumps({"users": ["alice"]}), encoding="utf-8")

        with self.assertRaises(TrackerError):
            load_group_users("legacy", "atcoder")

    def test_load_group_users_rejects_empty_selected_oj_users(self) -> None:
        group_file = Path("usergroup") / "empty.json"
        group_file.write_text(
            json.dumps({"atcoder": [], "cf": ["tourist"]}),
            encoding="utf-8",
        )

        with self.assertRaises(TrackerError):
            load_group_users("empty", "atcoder")

    def test_validate_contest(self) -> None:
        atcoder = AtCoderAdapter()
        cf = CodeforcesAdapter()

        self.assertEqual(atcoder.validate_contest("abc403"), "abc403")
        self.assertEqual(cf.validate_contest("2065"), 2065)
        with self.assertRaises(TrackerError):
            cf.validate_contest("abc403")

    def test_cache_has_done_contest_for_both_oj(self) -> None:
        atcoder = AtCoderAdapter()
        cf = CodeforcesAdapter()

        atcoder_submissions = [
            {"id": 1, "contest_id": "AbC100"},
            {"id": 2, "contest_id": "abc200"},
        ]
        cf_submissions = [
            {"id": 3, "contestId": 2065},
            {"id": 4, "contestId": 1000},
        ]

        self.assertTrue(tracker_service.cache_has_done_contest(atcoder, atcoder_submissions, "abc100"))
        self.assertFalse(
            tracker_service.cache_has_done_contest(atcoder, atcoder_submissions, "abc300")
        )
        self.assertTrue(tracker_service.cache_has_done_contest(cf, cf_submissions, 2065))
        self.assertFalse(tracker_service.cache_has_done_contest(cf, cf_submissions, 2066))


class CliOutputColorTest(unittest.TestCase):
    def test_run_colors_done_result_but_not_progress_lines(self) -> None:
        class FakeAdapter:
            name = "atcoder"

            def validate_contest(self, contest: str) -> str:
                return contest

        stdout = io.StringIO()
        with (
            patch("src.cli.get_adapter", return_value=FakeAdapter()),
            patch("src.cli.load_group_users", return_value=["alice", "bob"]),
            patch("src.cli.cache.ensure_cache_dir_exists"),
            patch(
                "src.cli.tracker.update_user_cache",
                side_effect=[
                    {"submissions": [{"id": 1}]},
                    {"submissions": []},
                ],
            ),
            patch(
                "src.cli.tracker.cache_has_done_contest",
                side_effect=[True, False],
            ),
            redirect_stdout(stdout),
        ):
            exit_code = run(["--oj", "atcoder", "-c", "abc403", "-g", "example"])

        self.assertEqual(exit_code, 0)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(lines[0], "checking user alice ...")
        self.assertEqual(lines[1], "checking user bob ...")
        self.assertEqual(lines[2], f"{ANSI_RED}alice done abc403{ANSI_RESET}")
        self.assertNotIn("\033[", lines[0])
        self.assertNotIn("\033[", lines[1])

    def test_run_colors_no_hit_result_in_green(self) -> None:
        class FakeAdapter:
            name = "cf"

            def validate_contest(self, contest: str) -> int:
                return int(contest)

        stdout = io.StringIO()
        with (
            patch("src.cli.get_adapter", return_value=FakeAdapter()),
            patch("src.cli.load_group_users", return_value=["tourist"]),
            patch("src.cli.cache.ensure_cache_dir_exists"),
            patch("src.cli.tracker.update_user_cache", return_value={"submissions": []}),
            patch("src.cli.tracker.cache_has_done_contest", return_value=False),
            redirect_stdout(stdout),
        ):
            exit_code = run(["--oj", "cf", "-c", "2065", "-g", "example"])

        self.assertEqual(exit_code, 0)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(lines[-1], f"{ANSI_GREEN}no users have done 2065{ANSI_RESET}")

    def test_main_colors_tracker_error_in_red_stderr(self) -> None:
        stderr = io.StringIO()
        with patch("src.cli.run", side_effect=TrackerError("boom")), redirect_stderr(stderr):
            exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertEqual(stderr.getvalue(), f"{ANSI_RED}error: boom{ANSI_RESET}\n")


if __name__ == "__main__":
    unittest.main()
