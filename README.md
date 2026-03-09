# oj-problem-tracker
A tool for ACM team coach to check whether team members have submitted in one or more target contests.

Supported OJ: AtCoder and Codeforces.

## Requirements

- Python 3.10+

## Prepare Group File

Create a group file in `usergroup/`, for example `usergroup/example.json`:

```json
{
  "atcoder": ["user1", "user2", "user3"],
  "cf": ["tourist", "Petr"]
}
```

## Usage

Check AtCoder users in a group for contests `abc403` and `abc404`:

```bash
python3 oj-problem-tracker.py --oj atcoder -c abc403 abc404 -g example
```

Check Codeforces users in a group for contests `2065` and `2066`:

```bash
python3 oj-problem-tracker.py --oj cf -c 2065 2066 -g example
```

Can also used in gym contests(e.g. gym104059):

```bash
python3 oj-problem-tracker.py --oj cf -c 104059 104060 -g example
```

Force refresh cache:

```bash
python3 oj-problem-tracker.py --oj atcoder -c abc403 abc404 -g example --refresh-cache
```

Show command help:

```bash
python3 oj-problem-tracker.py --help
```

## APIs

- AtCoder submissions API (primary):
  - `https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={user_id}&from_second={from_second}`
- AtCoder proxy fallback (used when primary returns HTTP 403):
  - `https://r.jina.ai/http://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={user_id}&from_second={from_second}`
- Codeforces submissions API:
  - `https://codeforces.com/api/user.status?handle={handle}&from={from}&count={count}`

Request pacing:

- AtCoder: 1 request per second
- Codeforces: 1 request per 2 seconds

## Cache Behavior

- Cache path:
  - AtCoder: `cache/atcoder/users/{user_id}.json`
  - Codeforces: `cache/cf/users/{user_id}.json`
- If cache directories do not exist, they are created automatically.
- If a user's cache file does not exist, it is created automatically by full fetch.
- Default minimum update interval is 24 hours (`86400` seconds).
- If cache is fresh (less than 24 hours), the program skips network update and uses local cache.
- If cache is stale (24 hours or more):
  - AtCoder updates from `next_from_second`.
  - Codeforces performs full refetch from page 1.
- `--refresh-cache` always forces refresh.
- When checking multiple contests, each user's cache is still updated only once per run.

## Output

- Per user start: `checking user <user_id> ...`
- Cache update in progress: `updating cache for <user_id> ...`
- Cache hit without update: `cache hit, skip update for <user_id>`
- For each contest, a hit is printed as `<user_id> done <contest_id>`
- If nobody in the group has done a contest, print `no users have done <contest_id>`

## Test

Run automated tests:

```bash
python3 -m unittest discover -s tests -v
```

Detailed test guide: `docs/test.md`
