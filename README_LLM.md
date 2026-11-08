# LLM Stack — llama.cpp + Open WebUI (Apple Silicon / M4 Max)

This repo's Mac has an **Apple M4 Max** (Metal 4, unified memory). There is no
NVIDIA/ROCm GPU here, so we use the **CPU/Metal** llama.cpp image and let
llama.cpp use Metal acceleration via the host. Docker Desktop on macOS exposes
the Apple GPU to containers through Metal — no `deploy.resources` GPU reservation
needed (that's an NVIDIA-only construct).

## Quick start

```bash
cd /Users/wilder/repo/harnesses/learn_hermes
docker compose up -d
```

Then:
1. Drop GGUF model files into `./models/` (or change the volume path).
2. Open Open WebUI at http://localhost:3000 and create an admin account.
3. Settings → Admin → Connections → OpenAI → Add:
   - URL: `http://host.docker.internal:8080/v1`
   - Auth: None
   - Provider: `llama.cpp` (under Advanced)

## Notes
- The `ghcr.io/ggml-org/llama.cpp:server` image is the CPU/Metal build; on
  Apple Silicon it uses Metal for acceleration automatically.
- Models are mounted read-only for safety.
- `--models-dir /models` makes llama.cpp scan the folder; Open WebUI will list
  every GGUF it finds.
- If models vanish from Open WebUI after a llama.cpp restart, re-add the
  connection (known quirk).
EOF