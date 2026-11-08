# Qwen 27B Coding Setup — The Through-Line, Applied to This Stack

Distilled action plan from the r/LocalLLM thread *"Local Qwen 27B is practically unusable for coding tasks."* The full curated comment notes are in [QWEN_27B_CODING_HELPFUL_COMMENTS.md](./QWEN_27B_CODING_HELPFUL_COMMENTS.md).

**The through-line:** a 27B being "unusable" is almost always a **setup problem, not the model** — context truncation, wrong quant, memory spillover, reasoning loops, and a heavy harness. Fix those, in order, verifying after each change.

**This stack already wins two of the battles:**
- You run **llama.cpp** (Metal, in Docker) — not Ollama, so there's no silent context cap to fix. ✅
- You drive it with **Hermes**, a lean autonomous agent harness — exactly the "ditch the bloated harness" advice. ✅

So for this box the work is: right-size context to unified memory, pick a real quant, tame the thinking, and drive it like a junior.

---

## Apply it here, in order

### 0. Baseline you can measure
Pick one small real task (fix one function). Record **tok/s** and **does it loop?**. Judge every change below against this.

### 1. Use a model that can actually code
The starter model in `./models/` is `qwen2.5-1.5b-instruct-q4_k_m.gguf` (~1.1GB) — fine for smoke tests, far too small for agentic coding. Pull a real coding model (Qwen 27B-class) into `./models/`:
```bash
cd /Users/wilder/repo/harnesses/learn_hermes
curl -L -o models/<qwen-27b-coder>-q4_k_m.gguf <huggingface-gguf-url>
docker compose restart llamacpp-server
```
Quant floor is **Q4_K_M**; go **Q5/Q6** if unified memory allows (see step 3).

### 2. Right-size context to UNIFIED memory (the Apple Silicon version of "don't spill to VRAM/SSD")
On M4 Max there's no separate VRAM — model weights + KV cache + the OS all share **unified memory**. Overshoot it and macOS swaps to SSD, which collapses tok/s (the thread's "6 → 1 tok/s" cliff).

Rules of thumb:
- Keep **weights + KV cache under ~70% of unified RAM**; watch **Activity Monitor → Memory Pressure** (stay green) and swap used (stay near 0).
- Rough costs: a Q4 27B is ~16GB of weights; KV cache grows with context and is often the surprise. **Start at 32K context, quantize the KV cache, raise only while tok/s holds.**

Add these to the `llamacpp-server` command in `docker-compose.yml`:
```yaml
    command: >
      --model /models/<qwen-27b-coder>-q4_k_m.gguf
      --ctx-size 32768
      --n-gpu-layers 999          # full Metal offload
      --flash-attn on
      --cache-type-k q8_0         # quantized KV cache
      --cache-type-v q8_0
      --host 0.0.0.0 --port 8080
```
Then `docker compose up -d` and re-run the baseline. If tok/s cratered, context/KV is too big for your memory — lower `--ctx-size` before anything else.

### 3. Pin the quant, then confirm
Re-run the baseline after setting a known quant. Accuracy should jump vs. a mystery/over-quantized build. If memory pressure is comfortable at 32K, try a higher quant (Q5_K_M/Q6_K) *or* a larger context — change one at a time.

### 4. Kill the overthinking loops
The top symptom ("spirals into a thought hole") is a reasoning problem, not raw incapability:
- Prefer the **"Swift" / reduced-thinking** build of the model if one exists (≈2x faster, similar quality).
- Set sampling explicitly in the request: lower temperature (e.g. `0.3–0.6`), `top_p ~0.9`, and cap/disable the thinking budget.
- If the chat template is wrong, loops get worse — make sure llama.cpp is using the model's correct template.

### 5. Hermes is your lean harness — use its leverage
Map the thread's harness advice onto Hermes features you already have:
- **Keep each task small** (thread: stay under ~32–64K context). Hermes finishes most tasks in 2–15 turns; let it.
- **Delegate to subagents** for single-responsibility chunks ("research X while you do Y") instead of one giant context.
- **`/compress`** (or auto-compression) before context bloat makes the model loopy — the thread warns models get "awfully loopy" past ~50% context.
- **Memory**: tell it your conventions once ("4-space, pytest, FastAPI") so they don't re-consume context every task.
- Point Hermes at the local llama.cpp endpoint (`http://host.docker.internal:8080/v1`), same connection Open WebUI uses.

### 6. Drive it like a junior
- One feature at a time; have it summarize/document each step.
- Use a **frontier model as planner/orchestrator** and Qwen as executor — e.g. plan/spec with Opus/Codex, let local Qwen do the grunt implementation, and have a second local instance review.
- Make the spec immaculate; **XML tags + CAPS** for section headers are followed far more reliably than plain markdown over long contexts.

---

## The verification loop (this is what "applying" means)
After **each** step, re-run your step-0 task and check two things:
1. **tok/s** — did it stay inside unified memory (no swap)?
2. **Did it loop?**

Change one knob, measure, keep or revert. That's how you find which fix mattered instead of changing six things and guessing.

## One-glance checklist
| # | Knob | This stack's setting |
|---|------|----------------------|
| 1 | Engine | llama.cpp (Metal) — already done ✅ |
| 2 | Model | real 27B coder, not the 1.5B starter |
| 3 | Quant | Q4_K_M floor, Q5/Q6 if memory allows |
| 4 | Context | start 32K, KV quantized, raise while tok/s holds |
| 5 | Memory | weights+KV < ~70% unified RAM; pressure green, no swap |
| 6 | Thinking | Swift / low temp / capped thinking budget |
| 7 | Harness | Hermes — small tasks, subagents, `/compress`, memory |
| 8 | Workflow | frontier planner + Qwen executor; immaculate spec; XML+CAPS |

> Not applicable to this Mac: Strata/unsloth custom builds and NVIDIA VRAM math from the thread — those are for ROCm/CUDA boxes. Stick with stock llama.cpp + Metal here.
