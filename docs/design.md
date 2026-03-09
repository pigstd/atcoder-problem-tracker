# 设计方式

## 目标

支持两类 OJ：`atcoder` 和 `cf`。两者共用同一套主流程：

1. 按 group 读取目标用户列表。
2. 先更新本地缓存。
3. 再只基于缓存判断是否做过一个或多个目标比赛。

差异点只在 OJ 适配层：

- AtCoder：支持基于 `next_from_second` 的增量抓取。
- Codeforces：缓存过期后执行全量重抓，不做基于时间游标的增量。

## 使用方式

### 命令行

AtCoder：

```bash
python3 oj-problem-tracker.py --oj atcoder -c abc403 abc404 -g example
```

Codeforces：

```bash
python3 oj-problem-tracker.py --oj cf -c 2065 2066 -g example
```

强制刷新缓存（忽略 24 小时更新间隔）：

```bash
python3 oj-problem-tracker.py --oj cf -c 2065 2066 -g example --refresh-cache
```

参数约束：

- `--oj`：必填，取值 `atcoder` 或 `cf`。
- `-c/--contest`：必填，支持一个或多个比赛参数，例如 `-c abc403 abc404`。
- 当 `--oj cf` 时，`--contest` 中的每个值都必须是纯数字（表示 `contestId`）。

### group 文件格式（不兼容旧版）

`usergroup/example.json`：

```json
{
  "atcoder": ["user1", "user2"],
  "cf": ["tourist", "Petr"]
}
```

规则：

- 根节点必须是对象。
- `atcoder` 和 `cf` 字段都必须存在，且类型都必须是数组。
- 运行 `--oj atcoder` 时读取 `atcoder` 数组；运行 `--oj cf` 时读取 `cf` 数组。
- 被选中的 OJ 用户列表为空时，报错并退出。

## 主流程设计

### 阶段 1：缓存更新

对被选中 OJ 的每个用户执行：

1. 读取缓存文件 `cache/{oj}/users/{user_id}.json`。
2. 若缓存不存在，初始化抓取。
3. 若缓存存在且距离 `last_updated_at` 小于 24 小时，跳过网络更新。
4. 若缓存过期或 `--refresh-cache`：
- AtCoder：从 `next_from_second`（或 0）继续拉取。
- Codeforces：从第一页开始全量重抓并覆盖 `submissions`。
5. 写回缓存文件。

### 阶段 2：比赛命中检查

不再请求网络，只扫描本地缓存 `submissions`。先完成所有用户的缓存更新，再按命令行给出的 contest 顺序逐个检查：

- AtCoder：`submission.contest_id.lower() == contest.lower()`。
- Codeforces：`submission.contestId == int(contest)`。

输出逻辑：

- `checking user <user_id> ...`
- 对每个 `contest_id`，命中用户输出 `<user_id> done <contest_id>`
- 若某个 `contest_id` 无人命中，输出 `no users have done <contest_id>`
- 多个比赛共用同一轮缓存更新，不会重复拉取同一用户缓存

## OJ 适配实现细节

### AtCoder 抓取

接口：

- 直连：`https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={user_id}&from_second={from_second}`
- 回退代理：`https://r.jina.ai/http://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={user_id}&from_second={from_second}`

规则：

- 直连返回 403 时切到代理。
- 每次请求后 `sleep 1` 秒，保持全局 1 req/s。
- 连续失败 5 次即报错退出。
- 分页推进：`from_second = max(epoch_second) + 1`。
- 返回空列表表示该用户抓取完成。

### Codeforces 抓取

接口：

- `https://codeforces.com/api/user.status?handle={handle}&from={from}&count={count}`

规则：

- 返回结构必须满足 `status == "OK"`，`result` 为数组。
- 每次请求后 `sleep 2` 秒，保持全局 0.5 req/s。
- 连续失败 5 次即报错退出。
- 分页方式：`from` 从 1 开始，固定 `count`（例如 1000），每轮 `from += count`。
- 当返回结果为空或不足 `count` 条时，认为该用户抓取完成。
- 过期更新策略：整份 `submissions` 全量重建，不走增量游标。

## 缓存设计

### 目录结构

- AtCoder：`cache/atcoder/users/{user_id}.json`
- Codeforces：`cache/cf/users/{user_id}.json`

目录不存在时自动创建。

### 缓存结构

AtCoder 缓存示例：

```json
{
  "version": 2,
  "oj": "atcoder",
  "user_id": "user1",
  "last_updated_at": "2026-03-04T02:34:56Z",
  "next_from_second": 0,
  "submissions": []
}
```

Codeforces 缓存示例：

```json
{
  "version": 2,
  "oj": "cf",
  "user_id": "tourist",
  "last_updated_at": "2026-03-04T02:34:56Z",
  "submissions": []
}
```

字段规则：

- `version`：缓存版本号。
- `oj`：缓存所属 OJ，必须与运行参数一致。
- `user_id`：用户名/handle。
- `last_updated_at`：UTC ISO 8601 时间。
- `next_from_second`：仅 AtCoder 使用。
- `submissions`：保存 API 返回原始提交对象。

去重规则：

- 使用提交 `id` 去重。
- AtCoder 增量合并时必须去重。
- Codeforces 全量重建可不依赖历史去重，但建议仍做一次去重保护。

## 项目结构（可扩展）

为支持后续新增更多 OJ，建议采用“调度层 + 核心层 + OJ 适配层”的结构。

当前实现目录：

```text
.
├── oj-problem-tracker.py
├── src
│   ├── cli.py
│   ├── core
│   │   ├── cache.py
│   │   ├── errors.py
│   │   └── tracker.py
│   ├── oj
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── atcoder.py
│   │   └── cf.py
├── tests
│   └── test_cache.py
├── cache
│   ├── atcoder
│   └── cf
└── usergroup
```

分层职责：

- 入口层（`oj-problem-tracker.py` / `src/cli.py`）：参数解析、主流程调度、统一输出与错误退出。
- 核心层（`src/core/`）：缓存读写、缓存校验、更新时间判断、通用重试框架与业务编排。
- OJ 适配层（`src/oj/*.py`）：API URL、响应解析、分页规则、比赛命中规则。
- 注册层（`src/oj/registry.py`）：`oj` 字符串到适配器的映射，避免在主流程中写分支。

建议统一 OJ 适配接口（可用 Protocol 或约定函数集合）：

- `validate_contest(contest: str) -> str | int`
- `validate_cache_fields(cache_data: dict, cache_file: Path) -> None`
- `update_submissions(user_id: str, existing_cache: dict | None, refresh_cache: bool) -> dict`
- `submission_matches_contest(submission: dict, contest: str | int) -> bool`

说明：

- OJ 适配层仍按“单个 contest”提供 `validate_contest` 和 `submission_matches_contest`。
- 多个 contest 的参数解析、批量校验和遍历输出由入口层负责。

新增 OJ 时的标准步骤：

1. 新增 `src/oj/<oj>.py` 并实现上述接口。
2. 在 `src/oj/registry.py` 注册新 OJ。
3. 在入口层补充 `--oj` 可选值和 contest 校验规则。
4. 新增缓存目录 `cache/<oj>/users/` 与对应缓存字段校验。
5. 在缓存更新阶段接入该 OJ 的抓取策略（增量或全量）。
6. 补充该 OJ 的单元测试（抓取、缓存、命中判定、参数校验）。

## 当前关键函数分布

- `src/cli.py`
- `parse_args`、`load_group_users`、`run`、`main`

- `src/core/cache.py`
- `ensure_cache_dir_exists`、`load_user_cache`、`write_user_cache`、`should_skip_cache_update`

- `src/core/tracker.py`
- `update_user_cache`、`cache_has_done_contest`

- `src/oj/base.py`
- `OJAdapter` 接口定义（contest 校验、缓存字段校验、抓取更新、命中判定）

- `src/oj/atcoder.py`
- `AtCoderAdapter`（403 代理回退、1 秒间隔、增量抓取与去重、`contest_id` 匹配）

- `src/oj/cf.py`
- `CodeforcesAdapter`（2 秒间隔、全量抓取与去重、`contestId` 匹配）

- `src/oj/registry.py`
- `get_adapter`、`available_oj_names`

## 异常处理

- group 文件不存在、JSON 非法、字段类型不对、选中 OJ 用户列表为空：报错并退出。
- `--oj cf` 但 `--contest` 中任一值非纯数字：报错并退出。
- 缓存文件损坏或字段不合法：报错并退出。
- API 连续 5 次失败：报错并退出，错误信息包含失败原因。
