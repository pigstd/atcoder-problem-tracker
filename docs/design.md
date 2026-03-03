# 设计方式

### 使用方式

指定比赛名字（例如 abc123），并且在 usergroup/ 目录中创建一个对应的 group，用 json 格式（例如 example.json）表示该 group 中的用户。

```bash
python3 atcoder-problem-tracker.py -c abc403 -g example
```

强制刷新某个 group 的缓存（忽略 24 小时更新间隔，重新从 0 全量抓取）：

```bash
python3 atcoder-problem-tracker.py -c abc403 -g example --refresh-cache
```

example.json 的格式如下：

```json
{
    "users": [
        "user1",
        "user2",
        "user3"
    ]
}
```

### 代码实现

在对应的 example.json 中，对于每个用户的用户名，用 https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={user_id}&from_second={unix_second} 这个 api 爬出所有的提交记录。

如果当前运行环境访问该 API 返回 403，则回退到只读代理
https://r.jina.ai/http://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={user_id}&from_second={unix_second}
来获取同样的数据。

**注意，该提交记录只提供从 unix_second 之后的至多 500 条，所以需要不断更新 unix_second 来爬取所有的提交记录。**

api 调用限制：每次调用后直接 sleep 1 秒（全局按 1 req/s 执行）。

然后如果检查到该用户的提交记录里面的 contest_id 满足 contest_id == abc403（大小写不敏感比较），那么就说明这个用户做过。

做过的定义：只要有提交就算做过，不要求 AC。

用户处理规则：

- 找到某个用户做过后，跳过该用户剩余提交记录，继续检查其他用户。
- 不是“找到一个就整体结束”，而是要扫描完 group 中所有用户。

输出格式：

- 开始检查某个用户时先输出：`checking user <user_id> ...`
- 用户做过时输出：`<user_id> done <contest_id>`
- 如果所有用户都没做过，输出：`no users have done <contest_id>`

分页规则：

- 初始 `from_second` 可从 0 开始。
- 每次返回提交后，更新为 `from_second = max(epoch_second) + 1`，避免重复。
- 当接口返回空列表时，说明该用户已拉取完，停止该用户查询。

失败重试规则：

- API 请求失败时重试。
- 如果连续 5 次失败，则停止程序并报错退出（错误信息需包含失败原因）。

输入与配置错误处理：

- group 文件不存在、JSON 格式错误、`users` 字段不存在或为空时，直接报错并退出（非 0 返回码）。

---

### 缓存设计

目标：把爬下来的数据缓存到本地，后续运行默认增量更新，避免每次都全量重爬。

缓存目录与文件：

- 每个用户一个缓存文件：`cache/users/{user_id}.json`。
- 若 `cache/users/` 目录不存在，程序启动时自动创建该目录。
- 不限制缓存大小，不做历史裁剪。

缓存文件结构（示例）：

```json
{
    "version": 1,
    "user_id": "user1",
    "last_updated_at": "2026-03-03T12:34:56Z",
    "next_from_second": 0,
    "submissions": []
}
```

字段规则：

- `last_updated_at`：该用户缓存最后一次成功更新的 UTC 时间（ISO 8601 字符串）。
- `next_from_second`：下次增量抓取起点。
- `submissions`：保存该用户所有已抓取提交，保存 API 返回的完整字段（不做字段裁剪）。

更新策略：

- 设定常量 `CACHE_MIN_UPDATE_INTERVAL_SECONDS`，默认值为 `86400`（24 小时）。
- 若某用户缓存文件不存在：自动创建该用户缓存文件，并从 `from_second=0` 全量抓取初始化。
- 若缓存存在且当前时间与 `last_updated_at` 间隔小于该常量：本次不进行网络更新，直接使用本地缓存处理。
- 若缓存存在且达到更新间隔：从 `next_from_second` 开始增量抓取，抓到空列表结束。
- 若使用 `--refresh-cache`：忽略更新间隔，直接从 `from_second=0` 全量重建该用户缓存。

增量抓取与去重规则：

- 分页仍按 `from_second = max(epoch_second) + 1` 推进。
- 新抓取数据写入缓存前，按提交 `id` 去重，避免重复存储。
- 成功更新后，刷新 `last_updated_at` 与 `next_from_second`。

主流程拆分为两阶段：

1. 更新缓存阶段：按上面的更新策略处理每个用户缓存。
2. 缓存处理阶段：只从本地缓存 `submissions` 判断目标 contest 是否做过。

异常处理补充：

- 若缓存文件损坏或格式不合法，程序报错并退出，避免静默使用错误数据。
