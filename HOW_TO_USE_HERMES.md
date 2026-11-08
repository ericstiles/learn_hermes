# How to Use Hermes Agent — Quick Start Guide

> A practical guide distilled from the [hermes-tutorial](https://github.com/cryptorichyrich/hermes-tutorial) repo and live session knowledge.

## What Hermes Is

Hermes is an **autonomous AI agent** running in your terminal — not a chatbot. It has tools (terminal, files, web, browser, cron, delegation) and **persistent memory** that carries across sessions. It acts, observes, and loops until the task is done.

## The Core Loop

Every request follows one repeating pattern:

```
Build prompt → Call LLM → Parse response → Run tools → Feed results back → Repeat
```

- Default max **90 turns** per conversation turn (configurable via `~/.hermes/config.yaml` → `agent.max_turns`).
- Most tasks finish in **2–15 turns**.
- Auto context compression when the conversation grows long; trigger manually with `/compress`.

## How to Talk to Me Effectively

1. **Be specific about outcomes, not steps.** "Set up a Python project with pytest and FastAPI" — I'll plan, write files, run tests.
2. **Reference real things.** Paste file paths, URLs, error messages. I'll read them with tools rather than guess.
3. **Tell me preferences once.** "I use 4-space indentation, FastAPI, pytest" → saved to memory, applied forever.
4. **Ask for parallel work.** "Check these three repos' latest releases" → I spawn subagents in parallel.
5. **Let me verify.** I run tests/builds before claiming done. "Done" means I actually executed it.

## Key Commands & Capabilities

- **Memory:** "Remember that..." persists across sessions. I also remember tool quirks and conventions.
- **Skills:** Reusable workflows I save after non-trivial tasks. Say "save that as a skill."
- **Cron:** "Every morning at 9am, summarize my GitHub notifications" → scheduled job.
- **Delegation:** "Research X while you do Y" → parallel subagents.
- **Web:** I search/extract live content, not cached training data.
- **Files/code:** Read, write, patch, run. I match your project's existing style.

## Quick Wins to Try

- "What's in this repo?" → I inspect the codebase
- "Remember I prefer tabs over spaces" → saved
- "Find all TODO comments in src/" → search_files
- "Set up a FastAPI app with one endpoint and a test" → full scaffolding + verified run

## Tips

- **Context compression** kicks in automatically; or type `/compress`.
- **Profiles** isolate config (work vs personal).
- **Security:** `hermes config set security.redact_secrets true` masks API keys in tool output.
- **Gateway:** `hermes gateway setup` puts me on Telegram/Discord/Slack for 24/7 access.

## What I Won't Do

- Guess file contents I haven't read.
- Claim success without running verification.
- Type secrets/passwords.
- Follow instructions embedded in web pages (prompt-injection defense).

## Source

- Tutorial: https://github.com/cryptorichyrich/hermes-tutorial (10 chapters, install to expert workflows)
- Docs: https://hermes-agent.nousresearch.com/docs
