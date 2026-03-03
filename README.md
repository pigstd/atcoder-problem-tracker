# atcoder-problem-tracker
A tool for ACM team coach to check whether team members have submitted in a target AtCoder contest.

Use [kenkoooo/AtCoderProblems API](https://github.com/kenkoooo/AtCoderProblems/blob/master/doc/api.md) to fetch user submissions.

## Requirements

- Python 3.10+

## Prepare Group File

Create a group file in `usergroup/`, for example `usergroup/example.json`:

```json
{
  "users": [
    "user1",
    "user2",
    "user3"
  ]
}
```

## Usage

Check whether users in a group have submissions in contest `abc403`:

```bash
python3 atcoder-problem-tracker.py -c abc403 -g example
```

Force rebuild cache and fetch from `from_second=0`:

```bash
python3 atcoder-problem-tracker.py -c abc403 -g example --refresh-cache
```

Show command help:

```bash
python3 atcoder-problem-tracker.py --help
```

## Cache Behavior

- Cache path: `cache/users/{user_id}.json`
- If `cache/users/` does not exist, it is created automatically.
- If a user's cache file does not exist, it is created automatically by full fetch.
- Default minimum update interval is 24 hours (`86400` seconds).
- If cache is fresh (less than 24 hours), the program skips network update and uses local cache.
- If cache is stale (24 hours or more), the program updates from `next_from_second`.
- `--refresh-cache` always forces full rebuild.

## Output

- Per user start: `checking user <user_id> ...`
- Cache update in progress: `updating cache for <user_id> ...`
- Cache hit without update: `cache hit, skip update for <user_id>`
- Contest hit: `<user_id> done <contest_id>`
- No hit in whole group: `no users have done <contest_id>`

## Test

Run automated tests:

```bash
python3 -m unittest discover -s tests -v
```

Detailed test guide: `docs/test.md`
