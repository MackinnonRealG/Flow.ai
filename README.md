# Flow

<!-- HQ:META
id: Flow
name: Flow
status: deployed
completion: 85
health: amber
category: Personal Tooling
stack: Swift (AppKit/AVFoundation), Python 3.12, Parakeet TDT 0.6B (MLX), Ollama qwen2.5:7b, SQLite, uv, launchd
entry: flow.py (Python watcher daemon) + Flow.app (Swift menu-bar app)
run: ./flowctl start
github: https://github.com/MackinnonRealG/Flow.ai
started: 2026-07
last_verified: 2026-07-13
connections: none
value: Cloud-free, always-on voice dictation everywhere on the Mac — Wispr Flow's feel with zero data leaving the machine
summary: A fully-local Wispr Flow clone for macOS — push-to-talk voice dictation with on-device STT (Parakeet/MLX) and LLM cleanup (Ollama), no cloud or API keys.
-->

> 🟡 **DEPLOYED** · **85% complete** · health amber · last verified 2026-07-13
> A fully-local Wispr Flow clone for macOS — hold a key, speak, and cleaned-up text types itself into any app, with all speech-to-text and LLM cleanup running on-device.

## What it is

Flow is a personal, entirely offline dictation tool for macOS. You hold Right ⌥, speak, and release; the cleaned-up text types itself into whatever app has focus. Two cooperating processes do the work: a native Swift menu-bar app (`Flow.app`) that owns the global hotkey, mic capture, and text injection, and a Python watcher daemon (`flow.py`) that runs speech-to-text (Parakeet TDT 0.6B via MLX), cleans the transcript with a local Ollama LLM (`qwen2.5:7b`), and logs everything to a local SQLite database. No cloud, no accounts, no API keys — speech, transcripts, and history never leave the machine.

## Status & completion — 85%

**Works today:**
- The full pipeline is **live and running right now** — menu-bar app, Python watcher, and Ollama are all up, with 12 real dictations logged across Slack, Mail, and iPhone (including a command-mode edit).
- Push-to-talk (hold Right ⌥), hands-free (double-tap Right ⌥ + silence auto-stop), and command mode (select text + hold Right ⌘ to voice-edit) — all implemented in Swift and exercised.
- On-device STT (Parakeet TDT 0.6B v2 / MLX) + Ollama `qwen2.5:7b` cleanup, with a sub-6-word "fast path" that skips the LLM for latency.
- Speech memory: SQLite dictation history, an auto-learned personal dictionary, an LLM-written style profile, and user corrections — all injected into the cleanup prompt so accuracy compounds.
- Context/tone matching (frontmost app captured per dictation), floating HUD pill, secure-input guard, 30-day audio retention, and iPhone dictation via an iCloud Drive inbox.
- Installed to `/Applications/Flow.app`; both LaunchAgents installed; `flowctl` manages the whole stack.

**Missing / not working:**
- **Native in-app STT via FluidAudio CoreML** (M3's last item) — deferred, blocked on installing Xcode (SwiftPM is broken under this machine's Command Line Tools, so the app is built with plain `swiftc`). The Python/MLX path is a full working substitute (~0.5 s vs the ~0.19 s the native ANE path would deliver).
- **No automated tests** anywhere in the repo (only a `test.wav` fixture). Correctness is validated by hand and by real use, not by a suite.
- **Path fragility introduced by the HQ consolidation move.** The daemon hardcodes its data dir as `~/Flow` (`Path.home() / "Flow"`) and the watcher LaunchAgent's `WorkingDirectory` is `/Users/connorsandford/Flow`, but the project now lives under `HQ/projects/Flow` and `~/Flow` no longer exists on disk. The currently-running watcher survived only because it predates the move and followed the renamed directory's inode (its live cwd is the new path). A reboot or any KeepAlive restart will fail to relaunch it, and a manual `uv run flow.py watch` would create a fresh, empty `~/Flow` rather than use the repo's `flow.db`/`recordings/`. Not yet reconciled (would need a `~/Flow` symlink, or an updated plist + `FLOW_DIR`).

**Why 85%:** All six milestones (M0–M5) plus logging/memory are functionally complete, backed by real usage data and an installed, running deployment — solidly in the "core works and runs, in use" band. It is held below 90 by the complete absence of automated tests and one acknowledged pending upgrade (native STT).

**Health amber:** It runs and clearly works at this moment, but the recent relocation silently broke the "always-on, self-healing appliance" guarantee the docs advertise (the hardcoded `~/Flow` no longer resolves for launchd), and there is no test coverage. Green would need the path / LaunchAgent reconciliation and/or a test pass; it is not red because the product itself is intact and currently live.

## Tech stack

- **App:** native Swift (AppKit + AVFoundation), macOS 14+, built via `swiftc` (SwiftPM disabled on this machine), ad-hoc code-signed for a stable TCC identity.
- **STT:** Parakeet TDT 0.6B v2 through `parakeet-mlx` (Apple MLX); `FLOW_STT` env var swaps in the multilingual v3 variant.
- **Cleanup LLM:** Ollama `qwen2.5:7b` via `/api/generate` (temperature 0, `keep_alive: 2h`); `FLOW_LLM` env override for a smaller/faster model.
- **Data:** SQLite (`flow.db`) — dictations, dictionary, profile, corrections.
- **Python 3.12**, dependencies managed by `uv` (parakeet-mlx, numpy, sounddevice, soundfile, requests, numba, llvmlite).
- **Always-on:** launchd LaunchAgents for the app and watcher. `ffmpeg` used for iPhone audio conversion and the test scripts.

## How to run

```bash
# One-time setup
brew install ollama ffmpeg && ollama pull qwen2.5:7b
uv sync                                   # Python env
./app/build-app.sh && open /Applications/Flow.app
# then grant Microphone, Input Monitoring, and Accessibility in
# System Settings -> Privacy & Security, and relaunch Flow.app

# Bring the whole stack up (Ollama + Flow.app + Python watcher)
./flowctl start
./flowctl status        # see what's running
./flowctl stop          # stop everything (returns at next login)

# Manual watcher alternative (no launchd):
uv run flow.py watch

# Utilities
uv run flow.py history -n 20
uv run flow.py correct "La Calhest" "localhost"
```

Note: the daemon reads/writes `~/Flow` by default. After the HQ move that path no longer exists, so verify it (or create a symlink to `HQ/projects/Flow`) before relying on auto-launch — see "Missing / not working" above.

## Project structure

- `flow.py` — Python watcher daemon: Parakeet STT → Ollama cleanup → SQLite log → notify → outbox; also `learn` / `correct` / `history` / `dict-*` subcommands.
- `m0_pipeline.py` — original M0 proof-of-concept, kept for reference.
- `flowctl` — start/stop/restart/status wrapper over the launchd jobs + Ollama + app.
- `app/Sources/Flow/*.swift` — menu-bar app: `HotkeyListener` (listen-only CGEventTap), `AudioRecorder` (AVAudioEngine, 16 kHz), `TextInjector` (clipboard paste + Accessibility), `HUD`, `AppDelegate` (hotkey state machine + outbox drain).
- `app/build-app.sh` — compiles and installs `Flow.app` via `swiftc`.
- `RESEARCH.md` — deep-research report on how Wispr Flow works + the original build plan.
- `RECOMMENDATIONS.md` — prioritized roadmap (Tier 1–3) with status notes.
- `flow.db`, `recordings/`, `outbox/`, `logs/` — private runtime data (gitignored); code expects these under `~/Flow`.
- `pyproject.toml` / `uv.lock` — Python dependencies (uv-managed).
- `~/Library/LaunchAgents/com.connorsandford.flow.{app,watcher}.plist` — always-on agents (installed).

## Connections

Flow is a standalone Personal Tooling utility with **no code-level integration** to other HQ projects — it shares no imports, services, or data with them (hence `connections: none`). Its relationship to the rest of the HQ is cross-cutting rather than structural: because it types into whatever app has focus, it can be used to dictate into any other project's editor, terminal, or chat while you work on it. It is versioned to its own private GitHub remote (`MackinnonRealG/Flow.ai`) and was recently folded into the HQ tree under `projects/Flow` by the repo-wide consolidation.

## Log

- 2026-07-13 — HQ README created; status assessed at 85% (deployed, health amber). Verified the app + watcher + Ollama are live with 12 real dictations logged; found the daemon and LaunchAgent still hardcode `~/Flow`, which the HQ consolidation move left dangling (documented above, not fixed — docs-only pass).

## Original project notes

_The project's original README, preserved verbatim below._

# Flow

A fully-local [Wispr Flow](https://wisprflow.ai) clone for macOS. Hold a key,
speak, release — cleaned-up text types itself into whatever app you're using.
No cloud, no accounts: speech-to-text, AI cleanup, and your entire dictation
history all run and stay on this machine.

Built 2026-07-05 on an M1 Pro MacBook (16 GB), macOS 26.5.

## How it works

```
Hold Right ⌥ ──► Flow.app records mic ──► ~/Flow/recordings/rec-<ts>.wav
                                                   │
                                          flow.py watch (daemon)
                                                   │
                    Parakeet TDT 0.6B (MLX) ── raw transcript      ~1.5s
                                                   │
                    qwen2.5:7b via Ollama ──── cleaned text        ~2s
                    (+ personal dictionary & style profile)
                                                   │
              ┌────────────────────────────────────┼──────────────────┐
              ▼                                    ▼                  ▼
        SQLite log                          macOS notification   ~/Flow/outbox/
     (~/Flow/flow.db)                                                 │
                                                            Flow.app pastes into
                                                            the focused app (⌘V)
```

Two cooperating processes:

- **Flow.app** (`app/`, native Swift menu-bar app): global hotkey via
  listen-only `CGEventTap`, 16 kHz mono WAV capture via `AVAudioEngine`, and
  text injection (save clipboard → paste → restore clipboard). Icons:
  🎤 idle · 🔴 recording · ⏳ transcribing · 📋 copied-only (no Accessibility).
- **flow.py watch** (Python daemon): watches the recordings folder, runs
  STT + LLM cleanup, logs everything, posts a notification, and writes the
  final text to the outbox for Flow.app to type.

## Setup from scratch

```bash
# 1. Dependencies (uv manages Python; models are fetched on first use)
brew install ollama ffmpeg        # ffmpeg only needed for the test scripts
ollama pull qwen2.5:7b

# 2. Python environment
cd ~/Flow && uv sync

# 3. Build and launch the menu-bar app
./app/build-app.sh
open /Applications/Flow.app

# 4. Grant permissions in System Settings → Privacy & Security:
#    Microphone, Input Monitoring, Accessibility — then relaunch Flow.app

# 5. Always-on: both processes are LaunchAgents (installed) — they start at
#    login and the watcher self-heals if it dies:
#      ~/Library/LaunchAgents/com.connorsandford.flow.app.plist
#      ~/Library/LaunchAgents/com.connorsandford.flow.watcher.plist
#    Watcher logs: ~/Flow/logs/watcher.log
#    (Manual alternative: uv run flow.py watch)
```

## Start / stop

```bash
./flowctl start     # bring everything up (Ollama + Flow.app + watcher)
./flowctl stop      # stop everything now (returns at next login)
./flowctl restart   # e.g. after editing flow.py or rebuilding the app
./flowctl status    # what's running
```

`stop` properly unloads the launchd jobs (a plain kill would be resurrected
by KeepAlive). Ollama is left running — it's a shared service and idles free.

## Daily use

Three interactions, all system-wide:

- **Hold Right ⌥**, speak, release → cleaned text types into the focused app
  (~2s for short utterances via the fast path, ~4–5s with LLM cleanup).
- **Double-tap Right ⌥** → hands-free mode: keeps listening until you tap
  Right ⌥ again or pause for ~2.5s (2 min cap).
- **Select text, hold Right ⌘**, speak an instruction ("make this more
  formal", "shorten this") → the edited text replaces the selection.

A floating HUD pill shows each state (listening / transcribing / what was
typed), plus the usual notification. Dictations are tone-matched to the app
you're in (casual for Slack, professional for Mail).

```bash
uv run flow.py watch           # the daemon (notifications + typing)
uv run flow.py watch --copy    # also copy each transcription to clipboard
uv run flow.py watch --no-inject  # log + notify only
uv run flow.py history -n 20   # read back your dictation history
uv run flow.py learn           # rebuild the speech profile now
uv run flow.py correct "La Calhest" "localhost"   # teach it a mishearing
uv run flow.py dict-add "Kubernetes" "Sandford"   # teach it your words
uv run flow.py dict-remove "..." ; uv run flow.py dict-list
uv run flow.py record -s 10    # mic test without the app
uv run flow.py process x.wav   # process an arbitrary audio file
FLOW_LLM=qwen2.5:3b uv run flow.py watch   # faster, lower-fidelity cleanup
FLOW_STT=mlx-community/parakeet-tdt-0.6b-v3 ...  # multilingual STT (drop-in)
FLOW_KEEP_DAYS=7 ...           # audio retention (default 30 days; transcripts kept forever)
```

## Dictate from your iPhone

No iOS app needed: an iOS **Shortcut** records your voice into iCloud Drive;
the Mac watcher transcribes it with the full pipeline (cleanup, dictionary,
history) and writes the text back next to it for your phone to read.

Build the Shortcut once (2 minutes, on the iPhone):

1. Shortcuts app → **+** → name it **Flow Dictate**
2. Add action **Record Audio** (set *Finish Recording: On Tap*)
3. Add action **Save File** → destination **iCloud Drive → Flow** (turn
   *Ask Where To Save* off)
4. *(Optional read-back)* add **Wait 15 s** → **Get File** from
   `Flow/<latest>.txt` → **Copy to Clipboard**

Then put it on your quick-access surfaces: **Action Button** (Settings →
Action Button → Shortcut), **Control Center** (add a "Shortcut" control),
Lock Screen widget, or a Home Screen icon.

Notes: transcription happens when the Mac is awake and online; iCloud sync
adds a few seconds each way. Transcripts land in `Files → iCloud Drive →
Flow` as `.txt`; processed audio is archived to `Flow/Processed/`. A native
iOS app (custom-keyboard style, like Wispr Flow's) would need Xcode plus an
Apple Developer account and is a possible future milestone.

## The speech memory

Every dictation is logged to `~/Flow/flow.db` (SQLite):

- `dictations` — timestamp, audio path, raw transcript, cleaned text, timings
- `dictionary` — your proper nouns and jargon (manual + auto-learned)
- `profile` — LLM-written notes on how you speak

The `learn` pass (auto-run every 5 dictations by the watcher) mines your
history for new vocabulary and style notes; both are injected into the cleanup
prompt, so accuracy on your voice compounds over time. Known mishearings get
corrected by dictionary proximity (e.g. "Olima" → "Ollama").

**Privacy note:** the database and recordings contain everything you've ever
dictated. They are `.gitignore`d — keep it that way.

## The cleanup prompt

The LLM instructions in [flow.py](flow.py) (`BASE_CLEANUP_PROMPT`) are the
heart of the product: filler removal, punctuation, spoken self-corrections
("50K, actually make that 75K" → "75K"). Tune them to your own speech.

## Repository map

| Path | What |
|---|---|
| `RESEARCH.md` | Deep-research report on Wispr Flow + the original build plan |
| `RECOMMENDATIONS.md` | Prioritized roadmap of recommended improvements |
| `flow.py` | Pipeline daemon: STT → cleanup → DB → notify → outbox |
| `m0_pipeline.py` | Original M0 proof-of-concept (kept for reference) |
| `app/` | Swift menu-bar app (hotkey, recording, text injection) |
| `app/build-app.sh` | Builds `app/Flow.app` (direct swiftc — see gotcha below) |
| `flow.db`, `recordings/`, `outbox/` | Your private data — not in git |

## Gotchas

- **SwiftPM is broken with this machine's Command Line Tools** (ManifestAPI
  link failure), so `build-app.sh` compiles with plain `swiftc`. Installing
  Xcode fixes SwiftPM and unblocks the FluidAudio native-STT upgrade.
- Ollama evicts idle models after ~5 min; `flow.py` passes `keep_alive: "2h"`
  so cleanup stays ~2s instead of paying a ~10s reload.
- Secure input fields (password boxes) silently refuse synthetic paste — by
  OS design.
- The `fn` key (Wispr Flow's default hotkey) is special-cased by macOS;
  Flow uses Right ⌥ instead.

## Milestone status

- ✅ **M0** — pipeline proof (record → Parakeet → Ollama → print)
- ✅ **M1** — menu-bar app: hold-to-talk hotkey + 16 kHz capture
- ✅ **Logging + memory** — SQLite history, personal dictionary, style profile
- ✅ **M2** — auto-typing into the focused app (hybrid: Python brain, Swift arm)
- 🔶 **M3** — polish: LaunchAgents (always-on, self-healing) ✅,
  short-utterance fast path (~1.5s, no LLM) ✅, learn-from-corrections
  (`flow.py correct`) ✅, HUD pill ✅, hands-free mode ✅, secure-input
  guard ✅, audio retention ✅; FluidAudio native STT pending Xcode install
- ✅ **M4** — context awareness: frontmost app captured per dictation,
  tone-matching prompt injection
- ✅ **M5** — command mode: select text + hold Right ⌘ + speak the edit
