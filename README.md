# LLM Stack: llama.cpp + Open WebUI (Apple Silicon)

This directory sets up a local, OpenAI-compatible LLM server using **llama.cpp**
running in Docker, plus **Open WebUI** as the chat frontend. Targeted at an
Apple Silicon Mac (M4 Max) — no NVIDIA/ROCm GPU reservation is needed; the
llama.cpp image uses Metal acceleration automatically.

## What was done

- Created `docker-compose.yml` with two services:
  - `llamacpp-server` — `ghcr.io/ggml-org/llama.cpp:server` on port 8080,
    scanning `./models` for GGUF files (mounted read-only).
  - `open-webui` — `ghcr.io/open-webui/open-webui:main` on port 3000.
- Downloaded a beginner model into `./models/`:
  `qwen2.5-1.5b-instruct-q4_k_m.gguf` (~1.1 GB).
- Added `models/README.md` with a download example for more models.

## Prerequisites

- macOS on Apple Silicon (M1/M2/M3/M4).
- Docker via Colima or Docker Desktop installed.
- ~2 GB free disk for the starter model (more for larger models).

## Installation

1. Start the Docker daemon (Colima):
   ```bash
   colima start
   ```
   (Or launch Docker Desktop.)

2. (Optional) Download additional models into `./models/`:
   ```bash
   curl -L -o models/<name>.gguf <huggingface-url>
   ```

## Running

```bash
cd /Users/wilder/repo/harnesses/learn_hermes
docker compose up -d
```

Check status:
```bash
docker compose ps
```

## First-time Open WebUI setup

1. Open http://localhost:3000 and create an admin account.
2. Go to **Settings → Admin → Connections → OpenAI → Add Connection**.
3. Set:
   - **URL:** `http://host.docker.internal:8080/v1`
   - **Auth:** None
   - **Provider:** `llama.cpp` (under Advanced)
4. Save. Your models in `./models/` should now appear in the model selector.

## Stopping

```bash
docker compose down
```

## Notes & troubleshooting

- The llama.cpp server scans `./models` for `.gguf` files; add/remove files and
  restart the container to refresh.
- If models vanish from Open WebUI after a llama.cpp restart, re-add the
  connection (known quirk).
- On non-Apple-Silicon (NVIDIA) hosts, switch the image to
  `ghcr.io/ggml-org/llama.cpp:server-cuda` and add a GPU reservation block.
- Strata (AMD/ROCm MoE engine) does not apply to this Mac; stick with
  stock llama.cpp here.
EOF