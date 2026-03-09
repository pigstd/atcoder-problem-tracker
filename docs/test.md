# 测试文档

## 1. 测试环境

- Python 版本：`Python 3.10+`（建议）
- 运行目录：项目根目录（包含 `oj-problem-tracker.py`）

## 2. 自动化测试（推荐）

执行命令：

```bash
python3 -m unittest discover -s tests -v
```

预期结果：

- 全部测试通过（`OK`）。
- 用例数量会随功能扩展增加，不再固定为 5。

建议覆盖点：

- group 新格式解析：`{"atcoder": [], "cf": []}`
- `--oj` 路由到对应用户列表
- `--contest` 多值解析
- `--oj cf` 时 `--contest` 中每个值的纯数字校验
- AtCoder：新建缓存、24 小时内跳过更新、过期后增量更新、按 `id` 去重
- Codeforces：新建缓存、24 小时内跳过更新、过期后全量重抓
- `--refresh-cache`：AtCoder/Codeforces 都会强制重抓
- AtCoder contest 匹配大小写不敏感
- Codeforces contest 匹配 `contestId` 数值相等
- 多比赛查询时每个用户缓存只更新一次
- 多比赛输出顺序与命令行中的 contest 顺序一致

## 3. 命令行参数检查

执行命令：

```bash
python3 oj-problem-tracker.py --help
```

检查点：

- 帮助信息中包含 `--oj` 参数说明
- 帮助信息中包含 `--contest` 支持多个参数的说明
- 帮助信息中包含 `--refresh-cache` 参数说明

## 4. 手动冒烟测试（可选）

准备：

在 `usergroup/` 下准备 group 文件，例如 `example.json`：

```json
{
  "atcoder": ["user1"],
  "cf": ["tourist"]
}
```

### AtCoder 冒烟

执行：

```bash
python3 oj-problem-tracker.py --oj atcoder -c abc403 abc404 -g example
```

可选执行（强制刷新）：

```bash
python3 oj-problem-tracker.py --oj atcoder -c abc403 abc404 -g example --refresh-cache
```

检查点：

- 首次运行后生成 `cache/atcoder/users/{user_id}.json`
- 再次运行且未超过 24 小时时，缓存不触发网络更新
- 过期后从 `next_from_second` 增量抓取
- 对 `abc403`、`abc404` 按顺序分别输出命中结果

### Codeforces 冒烟

执行：

```bash
python3 oj-problem-tracker.py --oj cf -c 2065 2066 -g example
```

可选执行（强制刷新）：

```bash
python3 oj-problem-tracker.py --oj cf -c 2065 2066 -g example --refresh-cache
```

检查点：

- 首次运行后生成 `cache/cf/users/{user_id}.json`
- 再次运行且未超过 24 小时时，缓存不触发网络更新
- 过期后会从第一页重新全量抓取并覆盖缓存
- 对 `2065`、`2066` 按顺序分别输出命中结果
