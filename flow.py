"""Flow: local dictation pipeline with history logging and speech memory.

Every dictation is transcribed (Parakeet on MLX), cleaned (Ollama), and logged
to a local SQLite database at ~/Flow/flow.db — audio path, raw transcript,
cleaned text, timings. Nothing leaves this machine.

The speech memory: `learn` mines your transcript history with the local LLM to
build a personal dictionary (your names, jargon, product terms) and a style
profile. Both are injected into every future cleanup prompt, so transcription
of *your* voice improves as the database grows. The watcher re-learns
automatically every LEARN_EVERY new dictations.

Usage:
  uv run flow.py watch            # daemon: auto-process new recordings from Flow.app
  uv run flow.py process X.wav    # transcribe + clean + log one file
  uv run flow.py record [-s 10]   # record from the mic, then process
  uv run flow.py learn            # rebuild speech profile from history now
  uv run flow.py correct "La Calhest" "localhost"   # teach it a mishearing
  uv run flow.py history [-n 10]  # show recent dictations
  uv run flow.py dict-add TERM... # manually add dictionary terms
  uv run flow.py dict-list
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
# 7b holds onto full sentences far better than 3b, which tends to drop
# clauses. Override with e.g. FLOW_LLM=qwen2.5:3b for speed over fidelity.
OLLAMA_MODEL = os.environ.get("FLOW_LLM", "qwen2.5:7b")
# Parakeet v2 is English-only; for multilingual use FLOW_STT with e.g.
# mlx-community/parakeet-tdt-0.6b-v3 (drop-in).
STT_MODEL = os.environ.get("FLOW_STT", "mlx-community/parakeet-tdt-0.6b-v2")
# Recordings older than this are deleted once transcribed (transcripts are
# kept forever in the DB). Audio is mostly liability, not value.
KEEP_DAYS = float(os.environ.get("FLOW_KEEP_DAYS", "30"))
SAMPLE_RATE = 16_000

FLOW_DIR = Path.home() / "Flow"
DB_PATH = FLOW_DIR / "flow.db"
RECORDINGS_DIR = FLOW_DIR / "recordings"
OUTBOX_DIR = FLOW_DIR / "outbox"  # Flow.app consumes these and types the text
LEARN_EVERY = 5  # watcher re-learns the speech profile every N new dictations

SCHEMA = """
CREATE TABLE IF NOT EXISTS dictations (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    wav_path   TEXT UNIQUE,
    raw        TEXT NOT NULL,
    cleaned    TEXT,
    duration_s REAL,
    stt_s      REAL,
    llm_s      REAL
);
CREATE TABLE IF NOT EXISTS dictionary (
    word     TEXT PRIMARY KEY,
    source   TEXT NOT NULL DEFAULT 'manual',
    added_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS profile (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS corrections (
    wrong      TEXT PRIMARY KEY,
    right      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

# Filler/correction markers: if a short utterance contains none of these, the
# LLM cleanup pass adds nothing and gets skipped (the latency fast path).
FILLERS = re.compile(
    r"\b(um+|uh+|erm|like|you know|i mean|actually|basically|no wait|sort of|kind of)\b",
    re.IGNORECASE,
)
FAST_PATH_MAX_WORDS = 6

BASE_CLEANUP_PROMPT = """\
You clean up raw speech-to-text transcripts for dictation. Rules:
- MOST IMPORTANT: when the speaker corrects themselves ("X, actually make
  that Y", "X, no wait, Y", "X, I mean Y"), output only Y. Never keep both
  the correction phrase and the old value.
- Remove filler words (um, uh, like, you know) and false starts.
- Add punctuation, capitalization, and paragraph breaks.
- Apply spoken self-corrections: replace ONLY the corrected value, keep the
  rest of the sentence intact.
- Preserve the speaker's words and meaning. Do not summarize, expand, shorten,
  or answer questions in the transcript.
- Output ONLY the cleaned text, nothing else.

Example input:
  Um, so the deadline is Tuesday, actually make that Thursday, and, uh, we need like three people on it.
Example output:
  So the deadline is Thursday, and we need three people on it.
"""

COMMAND_PROMPT = """\
You edit text according to a spoken instruction. Apply the instruction to the
text faithfully: keep the original meaning unless the instruction says
otherwise, and match the original's language. Output ONLY the edited text —
no preamble, no quotes, no explanation.
"""

LEARN_PROMPT = """\
You analyze a user's dictation transcripts to build a speech profile. From the
transcripts below, extract:

1. "dictionary": proper nouns, product names, technical jargon, and unusual
   terms the user actually says (correctly spelled/capitalized). These help a
   transcription cleaner spell them right. Exclude common English words.
   These are RAW machine transcripts, so they contain mishearings — if a term
   looks like a garbled version of a known term (or of an entry in the
   existing dictionary below), either output the correct spelling or skip it.
2. "style_notes": 2-4 short sentences describing how this speaker talks —
   their filler-word habits, formality, sentence length, recurring phrasing —
   written as guidance for a transcript cleaner.

Respond with JSON only: {"dictionary": ["..."], "style_notes": "..."}

Transcripts:
"""


# ─── database ────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    FLOW_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dictations)")}
    if "app" not in cols:
        conn.execute("ALTER TABLE dictations ADD COLUMN app TEXT")
    if "mode" not in cols:
        conn.execute("ALTER TABLE dictations ADD COLUMN mode TEXT DEFAULT 'dictate'")
    return conn


def read_meta(wav_path: str) -> dict:
    """Sidecar written by Flow.app at record time: app context + mode."""
    meta_path = Path(str(wav_path)[: -len(".wav")] + ".meta.json")
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    finally:
        meta_path.unlink(missing_ok=True)


def build_cleanup_prompt(conn: sqlite3.Connection, app_name: str | None = None) -> str:
    prompt = BASE_CLEANUP_PROMPT
    if app_name:
        prompt += (
            f"\nThe user is dictating into the app \"{app_name}\". Match that"
            " app's typical register — casual and brief for chat apps"
            " (Slack, Messages, Discord), professional for email (Mail,"
            " Outlook), plain and literal for editors, terminals, and"
            " documents. Adjust tone only; never add or remove content.\n"
        )
    words = [r[0] for r in conn.execute("SELECT word FROM dictionary ORDER BY word")]
    if words:
        prompt += (
            "\nThe speaker's personal dictionary — spell and capitalize these"
            f" exactly as written when they occur: {', '.join(words)}\n"
            "If a transcript word sounds like a mishearing of a dictionary term"
            " (e.g. 'Olima' for 'Ollama'), replace it with the dictionary term.\n"
        )
    row = conn.execute("SELECT value FROM profile WHERE key = 'style_notes'").fetchone()
    if row:
        prompt += f"\nAbout this speaker: {row[0]}\n"
    pairs = conn.execute(
        "SELECT wrong, right FROM corrections ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    if pairs:
        fixes = "; ".join(f"'{w}' means '{r}'" for w, r in pairs)
        prompt += f"\nKnown mishearings the user has corrected — always fix these: {fixes}\n"
    return prompt


def apply_corrections(conn: sqlite3.Connection, text: str) -> str:
    """Deterministic post-pass: replace known mishearings the user corrected."""
    for wrong, right in conn.execute("SELECT wrong, right FROM corrections"):
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
    return text


def needs_cleanup(raw: str) -> bool:
    """Fast path: short utterances with no fillers skip the LLM entirely."""
    return len(raw.split()) > FAST_PATH_MAX_WORDS or bool(FILLERS.search(raw))


# ─── pipeline stages ─────────────────────────────────────────────────────────

_stt_model = None


def transcribe(wav_path: str) -> tuple[str, float]:
    global _stt_model
    if _stt_model is None:
        from parakeet_mlx import from_pretrained
        _stt_model = from_pretrained(STT_MODEL)
    t0 = time.perf_counter()
    text = _stt_model.transcribe(wav_path).text.strip()
    return text, time.perf_counter() - t0


def ollama(system: str, prompt: str, as_json: bool = False) -> str:
    body = {
        "model": OLLAMA_MODEL,
        "system": system,
        "prompt": prompt,
        "stream": False,
        # keep the model loaded between dictations — otherwise Ollama evicts
        # it after ~5 min idle and the next cleanup pays a ~10s reload
        "keep_alive": "2h",
        "options": {"temperature": 0},
    }
    if as_json:
        body["format"] = "json"
    resp = requests.post(OLLAMA_URL, json=body, timeout=300)
    resp.raise_for_status()
    return resp.json()["response"].strip()


def wav_duration(path: str) -> float:
    import soundfile as sf
    info = sf.info(path)
    return info.frames / info.samplerate


def notify(message: str, title: str = "Flow") -> None:
    """Show the transcription as a macOS notification."""
    if len(message) > 200:
        message = message[:197] + "..."
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e", f'display notification "{safe}" with title "{title}"'],
        check=False, capture_output=True,
    )


def process(conn: sqlite3.Connection, wav_path: str, quiet: bool = False,
            notify_user: bool = False, copy_clipboard: bool = False,
            meta: dict | None = None) -> str | None:
    """Transcribe + clean one recording and log it. Returns the final text."""
    wav_path = str(Path(wav_path).resolve())
    meta = meta or {}
    app_name = meta.get("app_name")
    mode = meta.get("mode", "dictate")
    raw, stt_s = transcribe(wav_path)

    cleaned, llm_s = None, None
    if raw and mode == "command":
        # raw is a spoken instruction; apply it to the captured selection
        selection = meta.get("selection", "")
        t0 = time.perf_counter()
        cleaned = ollama(COMMAND_PROMPT,
                         f"Instruction: {raw}\n\nText to edit:\n{selection}")
        llm_s = time.perf_counter() - t0
    elif raw and needs_cleanup(raw):
        t0 = time.perf_counter()
        cleaned = ollama(build_cleanup_prompt(conn, app_name), raw)
        llm_s = time.perf_counter() - t0
    if raw:
        # deterministic safety net over both paths for user-corrected terms
        cleaned = apply_corrections(conn, cleaned if cleaned is not None else raw)

    conn.execute(
        "INSERT OR REPLACE INTO dictations"
        " (wav_path, raw, cleaned, duration_s, stt_s, llm_s, app, mode)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (wav_path, raw, cleaned, wav_duration(wav_path), stt_s, llm_s, app_name, mode),
    )
    conn.commit()

    final = cleaned or raw
    if notify_user:
        notify(final or "(silence)")
    if copy_clipboard and final:
        subprocess.run(["pbcopy"], input=final.encode(), check=False)

    if not quiet:
        mode = f"clean {llm_s:.2f}s" if llm_s is not None else "fast path"
        print(f"» {Path(wav_path).name}  (stt {stt_s:.2f}s, {mode})")
        print(f"  raw:     {raw or '(silence)'}")
        if cleaned:
            print(f"  cleaned: {cleaned}")
        sys.stdout.flush()
    return final


def learn(conn: sqlite3.Connection) -> None:
    """Mine transcript history into a personal dictionary + style profile."""
    rows = conn.execute(
        "SELECT raw FROM dictations WHERE raw != '' ORDER BY id DESC LIMIT 50"
    ).fetchall()
    if not rows:
        print("Nothing to learn from yet — dictate a few things first.")
        return

    existing = [r[0] for r in conn.execute("SELECT word FROM dictionary")]
    transcripts = "\n".join(f"- {r[0]}" for r in rows)
    prompt = LEARN_PROMPT
    if existing:
        prompt += f"(Existing dictionary: {', '.join(existing)})\n"
    prompt += transcripts
    reply = ollama(prompt, "Extract the speech profile as JSON.", as_json=True)
    try:
        data = json.loads(reply)
    except json.JSONDecodeError:
        print(f"Learn pass returned unparseable JSON, skipping: {reply[:200]}")
        return

    words = [w.strip() for w in data.get("dictionary", []) if isinstance(w, str) and w.strip()]
    for word in words:
        conn.execute("INSERT OR IGNORE INTO dictionary (word, source) VALUES (?, 'learned')",
                     (word,))
    notes = (data.get("style_notes") or "").strip()
    if notes:
        conn.execute(
            "INSERT INTO profile (key, value, updated_at) VALUES ('style_notes', ?, datetime('now','localtime'))"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (notes,),
        )
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM dictionary").fetchone()[0]
    print(f"Learned from {len(rows)} transcripts → dictionary now {total} terms.")
    if notes:
        print(f"Style notes: {notes}")


# ─── commands ────────────────────────────────────────────────────────────────

def prune_recordings(conn: sqlite3.Connection) -> None:
    """Delete transcribed audio older than KEEP_DAYS; transcripts stay in the DB."""
    cutoff = time.time() - KEEP_DAYS * 86_400
    known = {r[0] for r in conn.execute("SELECT wav_path FROM dictations")}
    pruned = 0
    for wav in RECORDINGS_DIR.glob("*.wav"):
        if wav.stat().st_mtime < cutoff and str(wav.resolve()) in known:
            wav.unlink(missing_ok=True)
            pruned += 1
    if pruned:
        print(f"Pruned {pruned} recording(s) older than {KEEP_DAYS:.0f} days"
              " (transcripts kept).", flush=True)


def cmd_watch(conn: sqlite3.Connection, copy_clipboard: bool = False,
              inject: bool = True) -> None:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Watching {RECORDINGS_DIR} — every dictation is logged to {DB_PATH}")
    print("Each transcription is shown as a notification"
          + (" and copied to the clipboard" if copy_clipboard else "")
          + (" and typed into the focused app via Flow.app." if inject else "."))
    print("Warming up the transcription model...", flush=True)
    prune_recordings(conn)
    known = {r[0] for r in conn.execute("SELECT wav_path FROM dictations")}
    since_learn = 0
    last_prune = time.time()
    while True:
        for wav in sorted(RECORDINGS_DIR.glob("*.wav")):
            path = str(wav.resolve())
            if path in known:
                continue
            # skip files still being written (finalized files stop growing)
            if time.time() - wav.stat().st_mtime < 1.0:
                continue
            final = process(conn, path, notify_user=True,
                            copy_clipboard=copy_clipboard, meta=read_meta(path))
            if inject and final:
                # Flow.app's outbox watcher picks this up and types it
                (OUTBOX_DIR / f"{Path(path).stem}.txt").write_text(final)
            known.add(path)
            since_learn += 1
            if since_learn >= LEARN_EVERY:
                learn(conn)
                since_learn = 0
        if time.time() - last_prune > 3600:
            prune_recordings(conn)
            last_prune = time.time()
        time.sleep(0.5)


def cmd_record(conn: sqlite3.Connection, seconds: float) -> None:
    import sounddevice as sd
    import soundfile as sf
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    out = RECORDINGS_DIR / f"rec-{time.strftime('%Y%m%d-%H%M%S')}.wav"
    print(f"● Recording {seconds:.0f}s — speak now...", flush=True)
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1)
    sd.wait()
    sf.write(str(out), audio, SAMPLE_RATE)
    process(conn, str(out))


def cmd_correct(conn: sqlite3.Connection, wrong: str, right: str) -> None:
    """Teach Flow a mishearing: fixes history, dictionary, and future cleanups."""
    conn.execute(
        "INSERT INTO corrections (wrong, right) VALUES (?, ?)"
        " ON CONFLICT(wrong) DO UPDATE SET right = excluded.right,"
        " created_at = datetime('now','localtime')",
        (wrong, right),
    )
    conn.execute("INSERT OR IGNORE INTO dictionary (word, source) VALUES (?, 'correction')",
                 (right,))
    conn.execute("DELETE FROM dictionary WHERE word = ? AND source = 'learned'", (wrong,))

    # retro-fix logged dictations that contain the mishearing
    fixed = 0
    for row_id, cleaned in conn.execute(
        "SELECT id, cleaned FROM dictations WHERE cleaned LIKE '%' || ? || '%'", (wrong,)
    ).fetchall():
        conn.execute("UPDATE dictations SET cleaned = ? WHERE id = ?",
                     (re.sub(re.escape(wrong), right, cleaned, flags=re.IGNORECASE), row_id))
        fixed += 1
    conn.commit()
    print(f"Corrected '{wrong}' → '{right}' (dictionary updated, {fixed} past dictation(s) fixed).")


def cmd_history(conn: sqlite3.Connection, n: int) -> None:
    rows = conn.execute(
        "SELECT created_at, duration_s, raw, cleaned FROM dictations ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    if not rows:
        print("No dictations logged yet.")
        return
    for created, dur, raw, cleaned in rows:
        print(f"[{created}] ({dur:.1f}s)")
        print(f"  {cleaned or raw or '(silence)'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("watch")
    p.add_argument("--copy", action="store_true",
                   help="also copy each transcription to the clipboard")
    p.add_argument("--no-inject", action="store_true",
                   help="log + notify only; don't type into the focused app")
    p = sub.add_parser("process"); p.add_argument("wav")
    p = sub.add_parser("record"); p.add_argument("-s", "--seconds", type=float, default=10)
    sub.add_parser("learn")
    p = sub.add_parser("correct")
    p.add_argument("wrong"); p.add_argument("right")
    p = sub.add_parser("history"); p.add_argument("-n", type=int, default=10)
    p = sub.add_parser("dict-add"); p.add_argument("terms", nargs="+")
    p = sub.add_parser("dict-remove"); p.add_argument("terms", nargs="+")
    sub.add_parser("dict-list")
    args = ap.parse_args()

    conn = db()
    if args.cmd == "watch":
        cmd_watch(conn, copy_clipboard=args.copy, inject=not args.no_inject)
    elif args.cmd == "process":
        process(conn, args.wav, meta=read_meta(str(Path(args.wav).resolve())))
    elif args.cmd == "record":
        cmd_record(conn, args.seconds)
    elif args.cmd == "learn":
        learn(conn)
    elif args.cmd == "correct":
        cmd_correct(conn, args.wrong, args.right)
    elif args.cmd == "history":
        cmd_history(conn, args.n)
    elif args.cmd == "dict-add":
        for term in args.terms:
            conn.execute("INSERT OR IGNORE INTO dictionary (word, source) VALUES (?, 'manual')",
                         (term,))
        conn.commit()
        print(f"Added {len(args.terms)} term(s).")
    elif args.cmd == "dict-remove":
        for term in args.terms:
            conn.execute("DELETE FROM dictionary WHERE word = ?", (term,))
        conn.commit()
        print(f"Removed {len(args.terms)} term(s).")
    elif args.cmd == "dict-list":
        for word, source in conn.execute("SELECT word, source FROM dictionary ORDER BY word"):
            print(f"  {word}  ({source})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
