# 测试文档

## 1. 测试环境

- Python 版本：`Python 3.10+`（建议）
- 运行目录：项目根目录（包含 `atcoder-problem-tracker.py`）

## 2. 自动化测试（推荐）

执行命令：

```bash
python3 -m unittest discover -s tests -v
```

预期结果：

- 看到 `Ran 5 tests` 且最终 `OK`。

当前自动化测试覆盖点：

- 新用户首次创建缓存文件
- 24 小时更新间隔内跳过网络更新
- 过期后从 `next_from_second` 增量更新
- 增量时按提交 `id` 去重
- `--refresh-cache` 触发从 `from_second=0` 全量重建
- contest 匹配大小写不敏感

## 3. 命令行参数检查

执行命令：

```bash
python3 atcoder-problem-tracker.py --help
```

检查点：

- 帮助信息中包含 `--refresh-cache` 参数说明。

## 4. 手动冒烟测试（可选）

准备：

- 在 `usergroup/` 下准备一个 group 文件，例如 `example.json`。

执行：

```bash
python3 atcoder-problem-tracker.py -c abc403 -g example
```

可选执行（强制刷新缓存）：

```bash
python3 atcoder-problem-tracker.py -c abc403 -g example --refresh-cache
```

检查点：

- 首次运行后生成 `cache/users/{user_id}.json`
- 再次运行且未超过 24 小时时，缓存不触发增量抓取
- 使用 `--refresh-cache` 时从 0 重新抓取并重建缓存
