# Cloning Wispr Flow Locally — Research Report & Build Plan

*Research date: 2026-07-05. Sources were gathered and claims extracted by a multi-agent research run; the adversarial verification pass was interrupted by a session limit, so claims below are single-pass extractions from the cited sources. Where multiple independent sources agree, that's noted — cross-source agreement is our substitute corroboration.*

---

## 1. How Wispr Flow actually works

**Interaction model** (corroborated by 4+ sources: [wisprflow.ai/features](https://wisprflow.ai/features), [Zapier review](https://zapier.com/blog/wispr-flow/), [tl;dv teardown](https://tldv.io/blog/wisprflow/), [Wispr Flow 101 guide](https://sidsaladi.substack.com/p/wispr-flow-101-the-complete-guide)):

- **Push-to-talk via a global hotkey** — default is the `fn` key on Mac. Hold, speak, release. There's also a hands-free mode (double-tap).
- **System-wide text insertion** — the cleaned-up text lands in whatever text field has focus, in any app (Gmail, Slack, Notion, Cursor, WhatsApp…). Flow has no editor of its own; it *is* the keyboard.
- **AI post-processing, not verbatim transcription.** This is the differentiator vs. plain dictation:
  - Strips filler words ("um", "like")
  - Infers punctuation, capitalization, paragraph breaks, and list formatting
  - Applies **spoken self-corrections**: "budget 50K, actually make that 75K" → outputs "budget 75K"
  - **Tone matching per app**: detects the frontmost app (Slack vs. Gmail vs. a doc) and adjusts formality
- **Personal dictionary** — auto-learns names/jargon when you correct a spelling; supports user-defined voice snippets.
- **Command mode** — natural-language edits of selected text ("delete that sentence", "make this shorter").

**Architecture — the critical fact for this project** (corroborated by 3 independent reviews: [voibe review](https://www.getvoibe.com/resources/wispr-flow-review/), [tl;dv](https://tldv.io/blog/wisprflow/), [weesperneonflow review](https://weesperneonflow.ai/en/blog/2026-02-09-wispr-flow-review-cloud-dictation-2026/)):

> **Wispr Flow is a cloud product.** Audio is sent to remote servers for both speech-to-text and the LLM rewriting step. There is no offline mode — no internet, no dictation. It also captures context from your active window (reportedly including periodic screenshots) and sends that to the cloud to power context-aware formatting.

So a local clone isn't a tweak of their model — it's a full replacement of their server-side pipeline with on-device equivalents. The upside: everything they do server-side is now reproducible locally with 2025-era open models.

---

## 2. The pipeline you need to recreate

Five components, in order:

```
┌────────────┐  ┌───────────┐  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ Global      │→│ Mic audio │→│ Local STT    │→│ Local LLM     │→│ Text          │
│ hotkey      │  │ capture   │  │ (Whisper/   │  │ cleanup       │  │ injection     │
│ (hold fn)   │  │ 16kHz PCM │  │  Parakeet)  │  │ (Ollama)      │  │ (paste/AX)    │
└────────────┘  └───────────┘  └─────────────┘  └──────────────┘  └──────────────┘
```

1. **Global hotkey capture** — a `CGEventTap` (or `NSEvent.addGlobalMonitorForEvents`) to detect key-down/key-up of the chosen hotkey anywhere in the OS. Requires **Accessibility / Input Monitoring** permission.
2. **Microphone capture** — `AVAudioEngine` (Swift) or equivalent; resample to 16 kHz mono PCM, which is what Whisper-family models expect. Requires **Microphone** permission.
3. **Speech-to-text** — a local STT engine (see §3). This **cannot be Ollama** — confirmed: Ollama serves LLMs (text-in/text-out, GGUF); it has no audio-model support. STT runs as its own engine.
4. **LLM cleanup/formatting** — this is where **Ollama** earns its place: POST the raw transcript to `http://localhost:11434/api/generate` with a system prompt that removes fillers, punctuates, applies self-corrections, and (later) adapts tone to the frontmost app.
5. **Text injection** — the standard trick used by every app in this space (documented in a [Hacking with Swift thread](https://www.hackingwithswift.com/forums/macos/how-can-i-programmatically-enter-text-to-an-arbitrary-application-first-responder/1612) and VoiceInk's source): save the clipboard, write your text to `NSPasteboard`, synthesize **⌘V** with `CGEvent`, then restore the clipboard. More surgical alternative: the Accessibility API (`AXUIElement`) to set the focused element's value directly — but paste-simulation is what works everywhere, including Electron apps and terminals.

---

## 3. Local STT on Apple Silicon — the engine choice

Key benchmark: [mac-whisper-speedtest](https://github.com/anvanvan/mac-whisper-speedtest) (MacBook Pro M4, 24 GB, 9 implementations):

| Engine | Latency (same clip) | Notes |
|---|---|---|
| **FluidAudio CoreML (Parakeet TDT)** | **~0.19 s** | Swift + CoreML, runs on the Apple Neural Engine; ~66 MB RAM footprint |
| parakeet-mlx | ~0.50 s | Python/MLX; ~2 GB RAM on GPU |
| mlx-whisper | ~1.02 s | ~2× faster than whisper.cpp on the same model ([independent Jan 2026 benchmark](https://notes.billmill.org/dev_blog/2026/01/updated_my_mlx_whisper_vs._whisper.cpp_benchmark.html)) |
| whisper.cpp (CoreML) | ~1.23 s | What VoiceInk ships; battle-tested |
| WhisperKit | ~2.22 s | Pure Swift, nice API |
| faster-whisper | ~6.96 s | **CPU-only on Mac** — great on NVIDIA, wrong choice here |

Accuracy ([macparakeet.com analysis](https://macparakeet.com/blog/whisper-to-parakeet-neural-engine/)): **Parakeet TDT 0.6B-v2** hits **1.69% WER** on LibriSpeech test-clean with 600 M params — *better* than Whisper Large-v3 Turbo (~2.2% WER, ~1 B params) on English, at 110–300× realtime. The multilingual v3 variant covers non-English at ~155–237× realtime.

**Takeaways:**
- English-first product → **Parakeet TDT** (via FluidAudio CoreML in Swift, or parakeet-mlx in Python). Fastest *and* most accurate.
- Need many languages or maximum ecosystem maturity → **whisper.cpp** or **mlx-whisper** with `large-v3-turbo`.
- Avoid faster-whisper on Mac; skip Apple's built-in `SFSpeechRecognizer` (weaker accuracy, rate limits, less control).
- Because these engines run 100–300× realtime, you don't need true streaming STT for a v1 — transcribing a 10-second utterance takes ~0.2–1 s after key-release, which already feels instant. Streaming is a v2 optimization.

---

## 4. Prior art — read these codebases

| Project | Stack | What to steal |
|---|---|---|
| **[VoiceInk](https://github.com/Beingpax/VoiceInk)** | Native Swift menu-bar app (macOS 14.4+), whisper.cpp as XCFramework, AudioToolbox capture, Accessibility-based paste, optional local-LLM enhancement | The closest open-source Wispr Flow analog. Its hotkey handling, paste-injection, and permissions flow are exactly the hard 20% of this project |
| **[Murmur](https://everydayaiwithbrian.com/blog/replace-wispr-flow.html)** | Whisper STT + **Ollama HTTP** cleanup (default `qwen2.5:7b`) | Proof of exactly your intended architecture — filler removal, punctuation, proper-noun capitalization, self-corrections via a local LLM prompt |
| **Handy** | Tauri/Rust, cross-platform, whisper.cpp | Reference if you ever want Windows/Linux |
| **Whispering** | Web-tech UI, pluggable STT backends | UI/UX reference |

---

## 5. Recommended v1 stack and build plan

### Stack decision

- **App shell: native Swift menu-bar app** (SwiftUI + AppKit). Reasons: `CGEventTap`, `AVAudioEngine`, `NSPasteboard`, and the TCC permission dance are all first-class in Swift and awkward everywhere else; Electron is heavy for an always-on utility; VoiceInk proves the pattern.
  - *Faster alternative if you want a working prototype today:* a Python daemon (`pynput` + `sounddevice` + `parakeet-mlx`/`mlx-whisper` + `requests` → Ollama + `pyautogui` paste). Fine for validating the pipeline; not what you ship.
- **STT: Parakeet TDT 0.6B v2 via FluidAudio CoreML** (Swift package). Fallback: whisper.cpp XCFramework with `large-v3-turbo`, VoiceInk-style.
- **Cleanup LLM via Ollama: `qwen2.5:7b`** (Murmur's default — good instruction-following for edit tasks). On ≤16 GB Macs, `llama3.2:3b` or `qwen2.5:3b` keep the whole pipeline under ~4 GB. Use the `/api/generate` endpoint, temperature ~0.2, and a strict "return only the cleaned text" system prompt.
- **Injection:** clipboard-save → `NSPasteboard` write → synthetic ⌘V via `CGEvent` → clipboard-restore.
- **Permissions to request (TCC):** Microphone + Accessibility (and Input Monitoring depending on how the hotkey tap is registered). App must be signed or the user must approve it in System Settings → Privacy & Security.

### Milestones

1. **M0 — pipeline proof (day 1):** shell script / Python: record 10 s → transcribe with parakeet-mlx → pipe through Ollama cleanup prompt → print. Validates model choices and the cleanup prompt before any app code.
2. **M1 — hold-to-talk skeleton:** Swift menu-bar app, `CGEventTap` on `fn` (key-down starts `AVAudioEngine` capture, key-up stops), buffer to 16 kHz PCM.
3. **M2 — transcribe + inject:** wire FluidAudio/Parakeet in-process; on transcript ready, paste-inject into the focused app. *This milestone alone ≈ raw dictation parity.*
4. **M3 — the "Flow" feel:** insert the Ollama cleanup step between STT and injection; iterate on the prompt (fillers, punctuation, self-corrections). Add a tiny floating "listening…" pill.
5. **M4 — context & dictionary:** read the frontmost app's bundle ID (`NSWorkspace.frontmostApplication`) and feed it to the prompt for tone matching; maintain a user dictionary injected into the prompt; settings UI for hotkey/model choice.
6. **M5 — command mode (stretch):** read the current selection via Accessibility, send selection + spoken instruction to Ollama, replace in place.

### Known risks

- **Cleanup latency**, not STT, will be the bottleneck: a 7B model on Ollama adds ~0.5–2 s for a paragraph. Mitigations: stream tokens and inject when done; use a 3B model; skip cleanup for very short utterances.
- **Secure input fields** (password boxes, some terminals with Secure Keyboard Entry) block synthetic paste — detect and degrade gracefully.
- **fn-key capture** is special-cased by macOS; most clones default to a chord like ⌥Space or right-⌘ instead. Start there.

---

## Sources

1. https://wisprflow.ai/features *(primary)*
2. https://github.com/anvanvan/mac-whisper-speedtest *(primary benchmark)*
3. https://github.com/Beingpax/VoiceInk *(primary code)*
4. https://zapier.com/blog/wispr-flow/
5. https://tldv.io/blog/wisprflow/
6. https://www.getvoibe.com/resources/wispr-flow-review/
7. https://weesperneonflow.ai/en/blog/2026-02-09-wispr-flow-review-cloud-dictation-2026/
8. https://sidsaladi.substack.com/p/wispr-flow-101-the-complete-guide
9. https://macparakeet.com/blog/whisper-to-parakeet-neural-engine/
10. https://notes.billmill.org/dev_blog/2026/01/updated_my_mlx_whisper_vs._whisper.cpp_benchmark.html
11. https://everydayaiwithbrian.com/blog/replace-wispr-flow.html *(Murmur — Whisper + Ollama clone)*
12. https://www.hackingwithswift.com/forums/macos/how-can-i-programmatically-enter-text-to-an-arbitrary-application-first-responder/1612
