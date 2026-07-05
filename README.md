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
open app/Flow.app

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
