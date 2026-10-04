# NInfer Runtime — Qwen3.8-27B GSQ-RCO IQ3_XXS（视觉版）

本机部署：RTX 4070 Ti **12GB**（sm_89）· Windows 11 · 2026-10-05 实测调优。

## 目录结构

```
E:\Apps\ninfer\runtime\
├─ engine\         预构建 sm_89 引擎（ninfer-serve.exe + CUDA 13 运行库 + FFmpeg 全套 DLL）
├─ engine.log      最近一次启动日志
├─ start_qwen3_8_27b_vision.bat   启动脚本（双击即用，自带杀旧实例）
└─ README.md       本文件
E:\Apps\models\
├─ Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp-vision.ninfer      模型构件（视觉版，10.3 GiB）
├─ Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp-vision.ninfer.conversion.json   转换报告
├─ Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf / mmproj-Qwen3.8-27B-BF16.gguf   转换输入
└─ convert-input\Qwen3.8-27B\   转换元数据（7 件套）
```

## 使用

- 启动：双击 `start_qwen3_8_27b_vision.bat`；健康检查 `http://127.0.0.1:8081/health`
- API：`http://127.0.0.1:8081/v1`（OpenAI Chat Completions / Responses、Anthropic Messages 兼容），模型名 `qwen3.8-27b`
- 视觉：OpenAI 标准多模态消息（`image_url` / `video_url` + base64 data URI）
- 完整部署指引（含下载地址、卡点、探测方法）：[部署指引.md](部署指引.md)
- 能力测试脚本：`tests\test_api.py`（用法见 [tests\README.md](tests/README.md)）
- 停止：任务管理器结束 ninfer-serve.exe，或再次运行脚本前它会自动杀旧实例

## 12GB 显存适配（实测探测记录）

按项目 A 部署文档 9.1/9.2 的探测法收敛，最终配置与 16GB 模板的差异及原因：

| 项目 | 16GB 模板（项目 A） | 本机 12GB 最终配置 | 原因 |
|---|---|---|---|
| 模型档位 | IQ3_S（权重 11.3 GiB） | **IQ3_XXS**（权重 9.71 GiB） | IQ3_S 权重本身超过 12GB 卡可用显存（11,056 MiB free < 11,571 MiB 权重），strict 必 FATAL |
| KV 精度 | rk8v4 | **rk4v4** | 每 8K tokens 省 ~140 MiB |
| CUDA Graphs | 开（默认） | **关（--no-cuda-graph）** | 本 profile 下 Graph 池 ~620 MiB，12GB 放不下 |
| 显存策略 | strict / default+768MiB headroom | default + **64 MiB** headroom | 权重载入后仅剩 ~980 MiB |
| 上下文 | 48K（视觉版） | **20K** | 见下方探测数据；MTP+ngram 保留（解码 93.9 tok/s，无 MTP 时 38.9 tok/s） |

探测数据（vision 构建、default 策略、rk4v4、无 graphs、headroom 64，权重载入后可用 ~975 MiB）：

| 上下文 | 结果 |
|---|---|
| 36,864（12/16 比例初值，rk8v4+graphs+MTP 全套） | FATAL：需 2.34 GiB + 768 MiB headroom，仅 936 MiB 可用 |
| 4,096（同全套） | FATAL：需 1.18 GiB + 768 MiB —— 固定开销 ~1.03 GiB |
| 32,768（无 MTP） | ✅ ready，free ~285 MiB（解码 38.9 tok/s） |
| 22,528（+MTP+ngram） | FATAL：差 ~15 MiB |
| **20,480（+MTP+ngram）** | ✅ **ready，free ~95 MiB（解码 93.9 tok/s）** ← 最终配置 |
| 16,384（+MTP+ngram） | ✅ ready，free ~166 MiB（更稳的备选） |

启动后 VRAM：11,834 / 12,282 MiB。验证：health 200 · /v1/models 正常 · 文本"1+1"→"2" ·
视觉红色图片→"Red" · 数数 1-200 全对。

### 真实媒体实测（2026-10-05）

连续 3 文本 + 3 真实图片 + 1 mp4 视频 + 收尾文本，全部 HTTP 200，VRAM 全程
11,873→11,889 MiB（±16 MiB 波动，无泄漏），health 始终 ok：

| 用例 | 耗时 | 输出 |
|---|---|---|
| 文本×3（数 1-50） | 1.8-2.1s | 88.5-100.2 tok/s，全对 |
| 银发动漫人物图（4MB PNG） | 11.2s | 描述正确（anime-style woman, white hair） |
| 花朵图（1.1MB PNG） | 11.9s | 描述正确（red rose, white background） |
| 黑夜鱼塘图（1.4MB PNG） | 12.4s | 描述正确（person with fishing rod at dark lake） |
| MiniMax 视频（1.3MB mp4） | 10.7s | 描述正确（anime girl praying, sunset, light beam） |

**视觉/视频请求注意**：默认 xhigh 思考会把 max_tokens 吃光导致正文为空（视频请求实测
200→600 tokens 全部被 reasoning 占用）。客户端传 `"reasoning_effort": "low"`（Chat
Completions 顶层字段，引擎原生支持）或显著调大 max_tokens。

## 调参提示

- 想要更长上下文：16K 档换 `--kv-dtype rk4v4` 不变、`--max-context 16384` 更稳；或关掉
  `--spec/--lookup-ngram` 后 `--max-context 32768`（解码降至 ~39 tok/s）
- 关闭吃显存的桌面程序（浏览器等）后再启动，可能解锁 22-24K + MTP
- 视觉塔在 CPU（`--vision-residency cpu`）：零显存开销，图片编码较慢；改 `resident` 需再降上下文
- 换上下文失败时看 engine.log 的 FATAL 行：`minimum Engine runtime reservation requires N bytes`，
  按比例缩 `--max-context`（128 的倍数）2-3 轮收敛

## 转换命令存档（以后换档位/重新转换用）

```bash
cd E:/Apps/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco
E:/Apps/convert-venv/Scripts/python.exe -u -m tools.convert \
  --model "E:/Apps/models/convert-input/Qwen3.8-27B" \
  --recipe qwen3_8_27b_gguf \
  --source "gguf=E:/Apps/models/Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf" \
  --source "vision=E:/Apps/models/mmproj-Qwen3.8-27B-BF16.gguf" \
  --components text,mtp,vision --proposal --device cpu --rows-per-chunk 512 \
  --name Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp-vision \
  --out "E:/Apps/models/Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp-vision.ninfer"
```

输入校验（SHA256）：IQ3_XXS GGUF `63f29a2189…4093262` · mmproj `13cb7bebcc…c0d3e16`。
转换实测 34.5s / 1195 objects / 1188 张量。
