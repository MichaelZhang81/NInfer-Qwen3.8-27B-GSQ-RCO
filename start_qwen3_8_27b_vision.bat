@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM NInfer + Qwen3.8-27B (GSQ-RCO IQ3_XXS) - VISION build
REM   Machine: RTX 4070 Ti 12GB (sm_89). Tuned 2026-10-05.
REM   Measured: decode 93.9 tok/s, VRAM 11,834/12,282 MiB.
REM
REM   Context 20K (rk4v4) + MTP x4 + ngram. CUDA Graphs are
REM   disabled: they cost ~620 MiB on this profile and do not
REM   fit in 12GB. Vision tower runs on CPU (zero extra VRAM).
REM
REM   ALTERNATIVES (edit flags below):
REM   - Safer fit, more free VRAM: --max-context 16384
REM     (about 165 MiB free instead of ~95 MiB)
REM   - Max context without MTP: --max-context 32768 and
REM     remove --spec/--lookup-ngram (decode drops to ~39 tok/s)
REM   - Closing GPU-hungry desktop apps frees VRAM and may allow
REM     22-24K context with MTP (22K missed by ~15 MiB)
REM
REM   Keep this file ASCII-only (GBK codepage pitfall).
REM ============================================================

REM ---------- paths ----------
set "ENGINE_DIR=E:\Apps\ninfer\runtime\engine"
set "MODEL_FILE=E:\Apps\models\Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp-vision.ninfer"
set "PORT=8081"

REM ---------- GPU ----------
set "CUDA_VISIBLE_DEVICES=0"

REM ---------- kill stale instances ----------
taskkill /F /IM ninfer-serve.exe >nul 2>&1
set "PORTBUSY="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do set "PORTBUSY=%%P"
if defined PORTBUSY (
  echo Killing stale listener on port %PORT%, pid !PORTBUSY! ...
  taskkill /F /PID !PORTBUSY! >nul 2>&1
  timeout /t 2 /nobreak >nul
)

cd /d "%ENGINE_DIR%"
echo Starting NInfer engine (VISION) ...
echo API: http://127.0.0.1:%PORT%/v1

ninfer-serve.exe "%MODEL_FILE%" ^
  --model-id qwen3.8-27b ^
  --vision --vision-residency cpu ^
  --max-context 20480 --prefill-chunk 128 ^
  --cuda-memory-policy default --kv-capacity auto --kv-headroom-mib 64 --kv-dtype rk4v4 ^
  --no-cuda-graph --host-cache-mib 6144 ^
  --default-max-tokens 0 ^
  --spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31 ^
  --temperature 1 --top-p 0.95 --top-k 20 --min-p 0 ^
  --preserve-thinking --default-reasoning-effort xhigh ^
  --port %PORT% --log-colours off

echo.
echo Engine exited.
pause
