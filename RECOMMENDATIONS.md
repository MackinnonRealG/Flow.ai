# Recommendations

My prioritized list of what to do next, based on the deep research into Wispr
Flow (see RESEARCH.md) and what we learned actually building Flow. Ordered by
impact-per-effort within each tier.

## Tier 1 — do these next (biggest wins)

> Status 2026-07-05 (evening): #2–#10 done. #1 pending — blocked on
> installing Xcode from the App Store (user action; no `mas` CLI here).
> #11 stays deferred by design (FLOW_STT env override makes it drop-in).
> #12 is an ongoing habit. #13: local commits done; GitHub push waiting on
> confirmation that the authenticated gh account (MackinnonRealG) is yours:
> `gh repo create Flow --private --source . --push`

1. **Install Xcode, then move STT into the Swift app via FluidAudio CoreML.**
   The benchmark that decided our stack showed Parakeet on the Apple Neural
   Engine at **~0.19s per utterance using ~66 MB of RAM**, versus ~0.5s and
   ~2 GB for the Python/MLX path we run today. This one change roughly halves
   end-to-end latency, frees 2 GB of your 16 GB, and removes the Python daemon
   from the critical path. It's blocked only by the broken CLT SwiftPM —
   installing Xcode fixes that.

2. **Make it always-on with LaunchAgents.** Today the watcher dies with its
   terminal and nothing survives a reboot. Two small plists in
   `~/Library/LaunchAgents` (one for Flow.app, one for `flow.py watch` with
   `KeepAlive`) turn Flow from a demo into an appliance. Without this, the
   first day the watcher isn't running, dictations silently go un-transcribed.

3. **Cut perceived latency with a fast path.** The 7B cleanup (~2s) is wasted
   on two-word utterances. Skip the LLM entirely when the raw transcript is
   short and already clean (< ~6 words, no fillers detected), and stream
   longer cleanups token-by-token. Wispr Flow feels instant because short
   commands ARE instant; this is the cheapest way to match that feel.

4. **Learn from corrections, not just raw transcripts.** This build's clearest
   lesson: the learn pass ingested mishearings ("Olima", even "ARM" for "um")
   because raw transcripts are polluted evidence. Wispr Flow's dictionary
   auto-updates when *you correct a word* — that's the trustworthy signal. Add
   `flow.py correct "La Calhest" "localhost"`: fixes the DB row, adds the
   right spelling to the dictionary, and (later) few-shots recent corrections
   into the cleanup prompt.

## Tier 2 — the features that make it feel like Wispr Flow

5. **Context awareness (M4).** Wispr Flow's tone matching — casual in Slack,
   formal in Mail — is just the frontmost app's bundle ID injected into the
   prompt. `NSWorkspace.shared.frontmostApplication` at record time, stored
   in a new DB column and passed to the cleaner. Cheap to build, and it's the
   feature reviewers consistently call the differentiator.

6. **A floating HUD pill.** The menu-bar emoji is easy to miss. A small
   always-on-top `NSPanel` near the cursor showing 🔴 recording → streaming
   partial text → done gives the confidence loop that makes people trust
   dictation. (Wispr, Superwhisper, and VoiceInk all converged on this UI.)

7. **Hands-free mode.** Wispr Flow's second interaction: double-tap the hotkey
   to lock recording, stop on next tap or ~2s of silence (simple RMS energy
   threshold — no ML needed). Essential for dictating anything longer than a
   sentence without holding a key.

8. **Command mode (M5).** Read the current selection via the Accessibility
   API, send selection + spoken instruction ("make this shorter") to Ollama,
   paste the result over the selection. The plumbing (selection read/write) is
   the same Accessibility work as injection — the model side is trivial.

## Tier 3 — robustness and hygiene

9. **Guard against secure-input fields.** Check `IsSecureEventInputEnabled()`
   before pasting; if active, keep the text on the clipboard and notify
   instead of silently losing the dictation into a password box.

10. **Audio retention policy.** Recordings accumulate forever (~2 MB/min).
    Add a watcher setting: keep WAVs N days (default 30), keep transcripts
    forever. The transcript is the value; the audio is mostly liability.

11. **Multilingual / accuracy fallback.** Parakeet v2 is English-only. If you
    ever dictate in another language, swap to Parakeet v3 (multilingual) or
    fall back to `mlx-whisper` large-v3-turbo for non-English — worth it only
    when the need is real, both are drop-in.

12. **Track model releases on two fronts.** The STT and cleanup models are
    both swappable constants. Re-run the bake-off occasionally: newer small
    LLMs on Ollama (the 3B-class catches up fast — retest sentence-dropping
    before trusting one) and newer Parakeet/Whisper releases. Our benchmarks
    live in RESEARCH.md; re-measure, don't assume.

13. **Commit early, commit often.** The repo now has its first commit; keep
    `flow.db`, `recordings/`, and `outbox/` out of git forever (already
    ignored). Consider a private GitHub remote as the offsite backup — the
    code carries no voice data.

## Explicitly not recommended (for now)

- **Electron/Tauri rewrite** — the native + Python hybrid is lighter and the
  hard parts (permissions, event taps) are already solved in Swift.
- **True streaming STT** — at 0.2–1.5s per utterance, batch transcription
  after key-release already feels instant; streaming adds complexity that
  only pays off for multi-minute dictations.
- **Cloud fallback of any kind** — the whole point of Flow is that nothing
  leaves the machine. Latency is better spent on Tier 1 items than on a
  network round-trip.
- **`fn`-key parity with Wispr Flow** — macOS special-cases it; Right ⌥
  works today. Revisit only if muscle memory demands it.
