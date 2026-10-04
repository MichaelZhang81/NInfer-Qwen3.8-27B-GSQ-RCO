#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NInfer 服务能力测试脚本（纯标准库，Python 3.8+，无需 pip 依赖）

用法:
  py -3.11 test_api.py all                      # 全部能力（不含视频）
  py -3.11 test_api.py all --video v.mp4        # 全部能力 + 视频
  py -3.11 test_api.py health                   # 单个子项
  py -3.11 test_api.py models
  py -3.11 test_api.py text
  py -3.11 test_api.py image [--image 图.png]
  py -3.11 test_api.py video --video 视频.mp4
  py -3.11 test_api.py speed
  py -3.11 test_api.py stability [--rounds 5]

常用选项:
  --base http://127.0.0.1:8081   服务地址
  --model qwen3.8-27b            模型名（服务端 --model-id 决定）
  --effort low                   媒体请求的 reasoning_effort（默认 low，避免思考吃光 max_tokens）
  --max-tokens N                 单请求输出上限
  --timeout S                    单请求超时秒数
  --rounds N                     稳定性测试轮数

退出码: 0 = 全部 PASS, 1 = 存在 FAIL。
"""
import argparse
import base64
import json
import subprocess
import struct
import sys
import time
import urllib.request
import zlib

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def make_red_png(path, w=256, h=256):
    """生成 256x256 纯红 PNG（视觉自检图，无 PIL 依赖）。"""
    rows = b""
    for _ in range(h):
        rows += b"\x00" + b"\xff\x00\x00" * w

    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return path


def vram():
    """nvidia-smi 显存快照；不可用时返回 None。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip()
    except Exception:
        return None


def http(method, path, body=None, timeout=300, base="http://127.0.0.1:8081"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None), time.time() - t0


def chat(body, timeout):
    st, resp, dt = http("POST", "/v1/chat/completions", body, timeout)
    if st != 200:
        return st, None, dt
    ch = resp.get("choices", [{}])[0]
    content = ch.get("message", {}).get("content", "")
    usage = resp.get("usage", {})
    return st, {
        "content": content,
        "finish": ch.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "reasoning_tokens": usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0),
    }, dt


def test_health(args):
    st, body, dt = http("GET", "/health", timeout=30, base=args.base)
    ok = st == 200 and isinstance(body, dict) and body.get("status") == "ok"
    record("health", ok, f"HTTP {st} {dt:.2f}s {json.dumps(body, ensure_ascii=False)[:120]}")
    return ok


def test_models(args):
    st, body, dt = http("GET", "/v1/models", timeout=30, base=args.base)
    ids = [m.get("id") for m in (body or {}).get("data", [])]
    ok = st == 200 and args.model in ids
    record("models", ok, f"HTTP {st} {dt:.2f}s ids={ids}")
    return ok


def test_text(args):
    st, r, dt = chat({
        "model": args.model,
        "messages": [{"role": "user", "content": "What is 1+1? Answer with a single number."}],
        "max_tokens": 64,
    }, args.timeout)
    ok = st == 200 and r and "2" in r["content"]
    record("text-basic", ok, f"HTTP {st} {dt:.2f}s content={r['content'][:60]!r}" if r else f"HTTP {st}")

    st, r, dt = chat({
        "model": args.model,
        "messages": [{"role": "user", "content": "Count from 1 to 50, one number per line, no other text."}],
        "max_tokens": 400,
    }, args.timeout)
    lines = (r["content"] or "").strip().splitlines() if r else []
    ok2 = st == 200 and lines and lines[-1].strip() == "50"
    record("text-count50", ok2,
           f"HTTP {st} {dt:.1f}s out={r['completion_tokens']} last={lines[-1] if lines else 'EMPTY'!r}"
           if r else f"HTTP {st}")
    return ok and ok2


def _media_request(args, part_type, mime, fname, question):
    b64 = base64.b64encode(open(fname, "rb").read()).decode()
    body = {
        "model": args.model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": part_type, part_type: {"url": f"data:{mime};base64," + b64}},
        ]}],
        "max_tokens": args.max_tokens,
    }
    if args.effort:
        body["reasoning_effort"] = args.effort
    return chat(body, args.timeout)


def test_image(args):
    fname = args.image
    builtin = False
    if not fname:
        fname = make_red_png("test_red256.png")
        builtin = True
        question = "What color is this image? Answer in one word."
    else:
        question = "Briefly describe this image in under 80 words."
    st, r, dt = _media_request(args, "image_url", "image/png", fname, question)
    if builtin:
        ok = st == 200 and r and bool(r["content"].strip()) and (
            "red" in r["content"].lower() or "红" in r["content"])
        record("image-red", ok,
               f"HTTP {st} {dt:.1f}s prompt={r['prompt_tokens']} content={r['content'][:80]!r}"
               if r else f"HTTP {st}")
    else:
        ok = st == 200 and r and bool(r["content"].strip())
        record("image-desc", ok,
               f"HTTP {st} {dt:.1f}s prompt={r['prompt_tokens']} content={r['content'][:80]!r}"
               if r else f"HTTP {st}")
    return ok


def test_video(args):
    if not args.video:
        print("[SKIP] video: 未提供 --video 路径")
        return True
    st, r, dt = _media_request(args, "video_url", "video/mp4", args.video,
                               "Briefly describe this video in under 80 words.")
    empty_warn = ""
    if r and not r["content"].strip() and r["reasoning_tokens"] >= r["completion_tokens"]:
        empty_warn = "（正文为空：思考吃光了 max_tokens，加 --effort low 或调大 --max-tokens）"
    ok = st == 200 and r and bool(r["content"].strip())
    record("video", ok,
           f"HTTP {st} {dt:.1f}s prompt={r['prompt_tokens']} out={r['completion_tokens']}"
           f"(reasoning={r['reasoning_tokens']}) content={r['content'][:80]!r}{empty_warn}"
           if r else f"HTTP {st}")
    return ok


def test_speed(args):
    st, r, dt = chat({
        "model": args.model,
        "messages": [{"role": "user", "content": "List the numbers from 1 to 200, one number per line, no other text."}],
        "max_tokens": 1200,
    }, args.timeout)
    if not r:
        record("speed", False, f"HTTP {st}")
        return False
    ct = r["completion_tokens"]
    speed = ct / dt if dt else 0
    lines = (r["content"] or "").strip().splitlines()
    ok = st == 200 and lines and lines[-1].strip() == "200"
    record("speed-count200", ok, f"HTTP {st} {dt:.1f}s out={ct} decode={speed:.1f} tok/s (wall, 含思考)")
    return ok


def test_stability(args):
    rounds = args.rounds
    lat, spd = [], []
    v0 = vram()
    ok_all = True
    for i in range(rounds):
        st, r, dt = chat({
            "model": args.model,
            "messages": [{"role": "user", "content": "Count from 1 to 50, one number per line, no other text."}],
            "max_tokens": 400,
        }, args.timeout)
        lines = (r["content"] or "").strip().splitlines() if r else []
        ok = st == 200 and lines and lines[-1].strip() == "50"
        ok_all &= ok
        speed = r["completion_tokens"] / dt if (r and dt) else 0
        lat.append(dt); spd.append(speed)
        print(f"  round {i+1}/{rounds}: HTTP {st} {dt:.2f}s out={r['completion_tokens'] if r else 0} "
              f"({speed:.1f} tok/s) {'OK' if ok else 'FAIL'}")
    v1 = vram()
    detail = (f"latency {min(lat):.2f}-{max(lat):.2f}s (mean {sum(lat)/len(lat):.2f}) | "
              f"speed {min(spd):.1f}-{max(spd):.1f} tok/s | VRAM {v0} -> {v1}")
    record("stability", ok_all, detail)
    return ok_all


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["all", "health", "models", "text", "image", "video", "speed", "stability"])
    ap.add_argument("--base", default="http://127.0.0.1:8081")
    ap.add_argument("--model", default="qwen3.8-27b")
    ap.add_argument("--image", default=None, help="图片路径；不传则用内置红图自检")
    ap.add_argument("--video", default=None, help="mp4 视频路径")
    ap.add_argument("--effort", default="low", help="媒体请求 reasoning_effort（'' = 不传该字段）")
    ap.add_argument("--max-tokens", type=int, default=200, help="媒体请求输出上限")
    ap.add_argument("--timeout", type=int, default=600, help="单请求超时秒数")
    ap.add_argument("--rounds", type=int, default=5, help="稳定性测试轮数")
    args = ap.parse_args()

    print(f"== NInfer 服务测试 | base={args.base} model={args.model} | {time.strftime('%F %T')} ==")
    print(f"== VRAM 起点: {vram() or 'nvidia-smi 不可用'}")
    t0 = time.time()

    tests = []
    if args.command == "all":
        tests = [("health", test_health), ("models", test_models), ("text", test_text),
                 ("image", test_image), ("speed", test_speed), ("video", test_video),
                 ("stability", test_stability)]
    else:
        tests = [(args.command, globals()[f"test_{args.command}"])]

    for name, fn in tests:
        if name == "stability" and args.command == "all":
            fn(args)  # 放最后
            break
        try:
            fn(args)
        except Exception as e:
            record(name, False, f"异常: {type(e).__name__}: {e}")

    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    n_fail = len(RESULTS) - n_ok
    print(f"== 汇总: {n_ok} PASS / {n_fail} FAIL | 总耗时 {time.time()-t0:.0f}s | "
          f"VRAM 终点: {vram() or 'n/a'} ==")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
