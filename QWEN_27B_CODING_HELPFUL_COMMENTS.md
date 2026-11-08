# Qwen 27B for Coding — Helpful Comments (Curated)

Source: r/LocalLLM thread *"Local Qwen 27B is practically unusable for coding tasks. Are we doing something wrong?"*

**What this file is:** the useful, actionable advice from the thread's comments, condensed and attributed. Pure jokes, snark, memes, sarcasm (`/s`), "nobody here knows what they're talking about" meta-commentary, and ads were dropped. Points are paraphrased to their actionable core, not reproduced verbatim.

**The original problem (context):** OP runs Qwen 3.8 27B (128K context) via **Ollama** on Ryzen 5 5500 / 32GB DDR4 / RTX 3090 24GB VRAM, using the *same* project structure and docs that work with Claude Sonnet. The local model gets lost, loops, and rarely completes basic coding tasks on its own.

The overwhelming consensus: **it's a setup problem, not the model** — specifically Ollama defaults, quant/VRAM, reasoning loops, and harness. Below are the concrete fixes.

---

## 1. Stop using Ollama (or at least fix its defaults)

- **Ollama silently caps context.** Out of the box it assumes a small context for Qwen 27B and truncates hard — you must create a config/modelfile that sets context to the full 128K, or it "will be a horrible experience." (u/Lopsided-Comedian-32, u/Express_Quail_1493, u/LegitimateCopy7)
- Move to **llama.cpp** — repeatedly called "the next obvious step." (u/InfiniteBlink, u/Repulsive_Initial308, u/Arkasha74)
- Alternatives people run successfully: **koboldcpp** (u/Arcane_Satyr), **LM Studio / LMStudio-Bionic** as an easier first step with better connection than Ollama (u/Express_Quail_1493), **vLLM** (u/DeedleDumbDee), **Strata** (u/byteJuggler, u/wegster, u/Sad-Chemist7118, u/stianhoiland).
- **unsloth-desktop** — backend is llama.cpp; their custom builds run faster, including on AMD. "Switched from ollama to unsloth and the difference is night and day." (u/575_Inverse, u/xsilas43, u/Damn-Sky)
- Suggested learning order: AnythingLLM → Ollama → LM Studio / Zed / Cursor → llama.cpp. Start simple, graduate to llama.cpp once you understand the knobs; don't start on bleeding-edge/buggy stacks. (u/Spearush, u/Arkasha74)
- Ollama *does* now support launching Qwen into agent harnesses, for a fairer comparison:
  ```
  ollama launch claude  --model qwen3.8
  ollama launch opencode --model qwen3.8
  ```
  (u/PuzzleheadedArm3732)

## 2. Name and raise your quant; KV-cache and sampling matter

- "We are missing a crucial information: **which quant?**" — the single most-repeated question. Post your quant, engine, temperature, and sampling settings. (u/initalSlide, u/HolaUsername, u/Apprehensive_Stop314, u/Pablo_the_brave, u/Oli_Luck)
- **Q4 is the floor.** A heavily quantized (e.g. 4-bit) model on 24GB sacrifices accuracy. Prefer Q6_K_L / Q8 if you can fit it. (u/aithosrds, u/NoOrdinaryBees, u/Erik-Zandros)
- Things to actually give people so they can help: **Quant, KV-cache quant, temperature.** (u/Oli_Luck)
- Working high-quality configs reported:
  - Unsloth **Q8_L + F16 KV** in llama.cpp (5080 + 5090 + 32GB RAM); Q4 also worked, just slightly more errors. (u/jefoce)
  - **oMLX Qwen3.8 27b-oQ4-FP16-MTP**, full context, run 24/7 for agentic tasks — compress the KV cache for speed without wrecking quality. (u/Patient_Tea_401)
  - Dual 3090 tensor-split, **Q8**, ~75 tok/s. (u/InfiniteBlink)
  - Strata + **IQ3_S / IQ3_XXS** FlashNext quant. (u/byteJuggler, u/stianhoiland)

## 3. 24GB VRAM + 128K context is the squeeze

- Qwen 27B is a **dense** model: it needs GB of VRAM roughly proportional to billions of parameters, and KV cache for 128K eats a lot more. 24GB likely **overflows to system RAM or SSD**, which collapses speed. (u/LegitimateCopy7, u/Badger-Purple, u/Pixelplanet5)
- Spilling out of VRAM took one user from ~6 tok/s to ~1 tok/s. (u/skifreek)
- Practical VRAM guidance: full context + **unquantized KV cache** wants ~**64GB VRAM** minimum for this model. (u/Patient_Tea_401)
- If you shrink context to fit (e.g. 32K on 32GB), note that **~32K is too little for real coding** — Claude Code's system prompt alone is ~27K before it says "Hello," and ~20K of that is guard rails. (u/skifreek, u/DystopianRealist, u/pjkm123987, u/Perfect-Campaign9551)
- To genuinely rival Sonnet locally, people point at **much bigger** models/hardware: DeepSeek 4.1, GLM 5.3, dual RTX 6000 / Blackwell Pro 6000, or renting on **vast.ai** first to learn what class you actually need. (u/Erik-Zandros, u/VorIMaldor, u/michinya)

## 4. Kill the overthinking / reasoning loops

- Qwen 3.8 "starts out great but once it gets some context loaded it inevitably spirals into a thought hole." This is the top symptom people report. (u/an0maly33, u/Minute-Plantain, u/DickVonShit)
- **Use the "Swift" variant** (reduced thinking) — it "drastically cut down on thinking, with a great deal of success" and runs ~2x faster for about the same quality. (u/Bagelsarenakeddonuts, u/DickVonShit, u/Lopsided-Comedian-32, u/w1ldr3dx)
- Or **turn the reasoning/thinking level down** (extra-high → medium/low). (u/skifreek, u/aithosrds)
- Repetitive loops are a classic sign of a **config / chat-template / token-streaming** problem, not raw incapability. (u/Express_Quail_1493)
- Switching to **Qwen Next Flash** (via Strata) gave "FAR more reasonable and concise" thinking. (u/an0maly33, u/pioo84, u/byteJuggler)

## 5. Harness is as important as the model

- "Harnessing is way more important than the model engine itself." Repeated by many. (u/Entire-Spite7776, u/lumpyspacebreh, u/Eja2001)
- **Claude Code is a bloated harness for a 128K model** — its large system prompt/guardrails crowd out your context. Try leaner ones. (u/Mysterious_Prune415, u/DystopianRealist)
- Harnesses people recommend for small/local models: **Qwen Code** (built specifically around Qwen) (u/PuzzleheadedArm3732), **Pi** (lightweight, low RAM) (u/Mysterious_Prune415, u/Emergency-Quiet3210, u/Creative_Bookkeeper9, u/w1ldr3dx), **opencode**, **Roo Code**, **cline**, **VS Code Copilot with BYOK sub-agents** (u/jefoce, u/Eja2001, u/Biotot).
- A better harness tuned for smaller models "would render better results"; several are building custom ones for exactly this. (u/Eja2001, u/lumpyspacebreh)

## 6. Treat it like a junior — small steps, subagents, tight context

- Small models need a **different workflow**: go step-by-step, feature-by-feature, like directing a junior; have it summarize and document each step. Don't hand it "build the whole app." (u/dreamyrhodes, u/ConsiderationFair657)
- **Keep tasks in the 0–64K context range.** Models get "awfully loopy" past ~50% of context; use **sub-agents** to manage/partition context. (u/aithosrds)
- Slice work into subagents with a **single responsibility** each (coding, code review, read-only DB, etc.). (u/jefoce)
- Use a **frontier model as planner/orchestrator** and Qwen as the executor:
  - Opus directly, with Qwen as a sub-agent that it keeps on task and kills when it loops — "massively" cut token usage. (u/Biotot)
  - Codex/Claude for planning + docs, Opus + Qwen for execution. (u/Biotot, u/sonicnerd14)
  - A "pre-check" instance of Qwen reviews the story/scope and sends issues back before wasting hours; a second instance validates against code-quality rules. (u/Bagelsarenakeddonuts)
- Qwen 27B "can write really good code, but it can't do that AND design AND troubleshoot AND keep the overall vision simultaneously — not enough context." Design elsewhere; let Qwen do the grunt work. (u/Bagelsarenakeddonuts, u/InfiniteBlink)

## 7. Prompting tricks that help small models

- **XML tags + CAPS** for section headers are followed far more strictly than plain markdown, even over 200K+ distances — "resulting in higher success rates over long distances." Ask a cloud model to help you build these prompts. (u/jefoce)
- Make the **spec immaculate**; encode explicit code-quality rules (e.g. justify every `unsafe` in Rust) that a second instance validates. (u/Bagelsarenakeddonuts)
- Structure for local: plan features to local files → chunk the job into small logical steps → have an "auditor" instance review. (u/Oli_Luck)
- Expose only a **list of utilities** first, then drill into the specific one (2 calls) to conserve context vs. dumping everything. (u/Creative_Bookkeeper9)
- Context caching + a **shared prefix** (story context, files, code standards) across all agents "massively speeds things up." (u/Bagelsarenakeddonuts)

## 8. Reset expectations

- A 27B is roughly **Haiku-tier**, not Sonnet-tier; the closest-to-Sonnet open models are in the ~400B–500B range. It may take 5–10 local prompts to do what Claude does in one. (u/yellowsockss, u/Eja2001, u/aithosrds)
- It **won't** match a frontier model, but at Q6+ with the right engine/harness it "does get the job done." Many report real success (tens of thousands of lines of reviewed Rust, Android apps, a Pac-Man clone, fixing bugs Claude missed). (u/HolaUsername, u/Bagelsarenakeddonuts, u/pioo84, u/soulman901, u/dsdt)
- For a well-defined workflow with a custom harness, 27B is viable; for open-ended autonomy, use a bigger model. "A bigger model compensates for a good chunk of laziness and skill issue." (u/michinya)

---

## Fully-worked reference setups from the thread

- **u/stianhoiland** — 4070 Super 12GB / 32GB DDR5 / Qwen3.8-Flash-Next (125B A6B, 51B N-grams) / IQ3_S / Strata 0.2.6 / CUDA 13. Slow prefill but usable and rock solid. Key flags:
  ```
  --model IQ3_S
  --model-path "$MODELS/Strata/models"
  --port 8000
  --access local
  --parallel 1
  --vision off
  --mtp off
  --context 262144
  --kv k8v4
  --set kv-resident=20480
  --tune skip
  ```
- **u/Sad-Chemist7118** — Strata, 272K context, 16GB GPU (4080) + 64GB RAM, PCIE4 SSD, ~70–80 tok/s, Claude-like TTFT with a ~50K first prompt. "As good as Opus 4.5 from ~1 year ago."
- **u/jefoce** — Unsloth Q8_L + F16 KV in llama.cpp, 5080 + 5090 + 32GB RAM.
- **u/rkcth** — add RAM (2×32GB DDR4 ~$300, or 4×32GB), then run Qwen 3.8 Flash Next on Strata with the 3-bit quant.

## One-line diagnostic checklist

1. Which **quant**? (Q4 floor; prefer Q6_K_L/Q8)
2. Which **engine**? (get off Ollama, or fix its context modelfile; prefer llama.cpp/Strata/unsloth)
3. What **context size** is actually loaded? (128K may be overflowing 24GB VRAM → SSD → crawl)
4. **KV-cache** quant + **temperature** / sampling set?
5. **Thinking level** — use Swift / lower reasoning to stop loops.
6. Which **harness**? (ditch Claude Code's heavy prompt; try Qwen Code / Pi / opencode)
7. Are you driving it like a **junior** — small steps, subagents, tight context, frontier planner?
