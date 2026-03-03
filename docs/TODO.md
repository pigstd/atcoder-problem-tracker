接下来完成缓存实现（基于已确认设计）：

- 每个用户使用一个缓存文件：`cache/users/{user_id}.json`。
- 若 `cache/users/` 目录不存在，程序自动创建。
- 若某用户缓存文件不存在，程序自动创建该文件并做首次全量初始化。
- 缓存字段包含：`version`、`user_id`、`last_updated_at`、`next_from_second`、`submissions`。
- `submissions` 保存 API 返回的完整字段，不做裁剪，不限制缓存大小。
- 增量更新游标使用 `next_from_second`，按 `from_second = max(epoch_second) + 1` 推进。
- 记录更新间隔常量：`CACHE_MIN_UPDATE_INTERVAL_SECONDS`（默认 86400 秒）。
- 当“当前时间 - last_updated_at < 更新间隔”时，本次不更新缓存，直接用本地缓存处理。
- 当达到更新间隔时，从 `next_from_second` 继续增量拉取并写回缓存。
- 新增 `--refresh-cache` 参数，强制从 `from_second=0` 全量重建缓存。
- 程序主流程拆分为两阶段：
  - 更新缓存阶段
  - 从缓存处理判定阶段
