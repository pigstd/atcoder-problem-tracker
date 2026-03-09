from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from src.core import cache
from src.core import tracker
from src.core.errors import TrackerError
from src.oj.registry import available_oj_names, get_adapter

ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_RESET = "\033[0m"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether users in a group have submissions in one or more target contests."
    )
    parser.add_argument(
        "--oj",
        required=True,
        choices=available_oj_names(),
        help="Online judge to query",
    )
    parser.add_argument(
        "-c",
        "--contest",
        required=True,
        nargs="+",
        help="One or more contest IDs to check",
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
        help="Force refresh cache, ignoring update interval.",
    )
    return parser.parse_args(argv)


def _validate_group_users(data: Any, group_file: Path) -> dict[str, list[str]]:
    if not isinstance(data, dict):
        raise TrackerError(f"invalid group format in {group_file}: root must be an object")

    users_by_oj: dict[str, list[str]] = {}
    for oj in available_oj_names():
        users = data.get(oj)
        if users is None:
            raise TrackerError(f"invalid group format in {group_file}: missing '{oj}' field")
        if not isinstance(users, list):
            raise TrackerError(f"invalid group format in {group_file}: '{oj}' must be a list")
        if not all(isinstance(user, str) and user.strip() for user in users):
            raise TrackerError(
                f"invalid group format in {group_file}: every '{oj}' user must be a non-empty string"
            )
        users_by_oj[oj] = users

    return users_by_oj


def load_group_users(group_name: str, oj: str) -> list[str]:
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

    users_by_oj = _validate_group_users(data, group_file)
    users = users_by_oj[oj]
    if not users:
        raise TrackerError(f"invalid group format in {group_file}: '{oj}' must not be empty")

    return users


def colorize(text: str, color: str) -> str:
    return f"{color}{text}{ANSI_RESET}"


def print_colored(text: str, color: str, *, file: TextIO | None = None) -> None:
    print(colorize(text, color), file=file, flush=True)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    adapter = get_adapter(args.oj)
    target_contests = [adapter.validate_contest(contest) for contest in args.contest]
    users = load_group_users(args.group, args.oj)
    cache.ensure_cache_dir_exists(adapter.name)

    user_caches: dict[str, dict[str, Any]] = {}
    for user_id in users:
        print(f"checking user {user_id} ...", flush=True)
        user_caches[user_id] = tracker.update_user_cache(adapter, user_id, args.refresh_cache)

    for raw_contest, target_contest in zip(args.contest, target_contests):
        found_any = False
        for user_id in users:
            if tracker.cache_has_done_contest(adapter, user_caches[user_id]["submissions"], target_contest):
                print_colored(f"{user_id} done {raw_contest}", ANSI_RED)
                found_any = True

        if not found_any:
            print_colored(f"no users have done {raw_contest}", ANSI_GREEN)

    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except TrackerError as exc:
        print_colored(f"error: {exc}", ANSI_RED, file=sys.stderr)
        return 1
