# 服务能力测试脚本

`test_api.py`：纯 Python 标准库（无 pip 依赖，Python 3.8+ 任意解释器可用）。

## 快速开始

```bat
REM 服务启动后（start_qwen3_8_27b_vision.bat），运行：
py -3.11 E:\Apps\ninfer\runtime\tests\test_api.py all
py -3.11 E:\Apps\ninfer\runtime\tests\test_api.py all --video E:\downloads\MiniMax_H3_00003_.mp4
```

## 子命令

| 命令 | 验证内容 | 通过标准 |
|---|---|---|
| `health` | GET /health | 200 且 status=ok |
| `models` | GET /v1/models | 200 且列出 qwen3.8-27b |
| `text` | "1+1"（期望 "2"）+ 数 1–50 | 答案含 2；末行是 50 |
| `image` | 内置纯红图自检（或 `--image 图.png` 描述） | 红图答案含 red/红；指定图描述非空 |
| `video` | `--video 视频.mp4` 描述 | 描述非空（视频约 400 prompt tokens/1.3MB） |
| `speed` | 数 1–200（max_tokens 1200） | 末行 200；正常 80–110 tok/s（wall，含思考） |
| `stability` | `--rounds N` 轮数 1–50 | 每轮全对；延迟/速度统计 + 显存前后对比 |
| `all` | 依次执行全部（视频需 `--video`） | 全部 PASS，exit code 0 |

## 常用选项

```
--base http://127.0.0.1:8081   服务地址（默认本机）
--model qwen3.8-27b            请求模型名
--effort low                   媒体请求思考档（默认 low；'' = 不传）
--max-tokens 200               媒体请求输出上限
--timeout 600                  单请求超时秒数
--rounds 5                     稳定性轮数
```

## 已知经验（测试中发现）

1. **媒体请求默认 `--effort low`**：xhigh 思考会把 max_tokens 全吃光导致正文为空
   （usage 的 reasoning_tokens == completion_tokens 且 content 空即是此现象）。
2. 红图自检会生成 `test_red256.png`（本目录），可安全删除。
3. 显存快照依赖 nvidia-smi 在 PATH；不存在时自动跳过。
4. 服务为单并发（--max-concurrency 1），连续请求即为串行排队，稳定性测试的延迟统计
   已含排队效应。
