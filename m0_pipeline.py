"""M0 pipeline proof: record -> Parakeet STT -> Ollama cleanup -> print.

Validates the full local dictation pipeline before any app code exists.

Usage:
    uv run m0_pipeline.py                 # record 10s from the mic
    uv run m0_pipeline.py --seconds 5     # shorter recording
    uv run m0_pipeline.py --file test.wav # skip the mic, use an audio file
    uv run m0_pipeline.py --raw           # skip Ollama cleanup (STT only)
"""

import argparse
import sys
import tempfile
import time

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"
STT_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
SAMPLE_RATE = 16_000

# ─── The cleanup prompt ───────────────────────────────────────────────────────
# TODO(connor): this prompt IS the product — Wispr Flow's entire quality gap
# over raw dictation lives here. This default works, but tune it with your own
# dictation style: what fillers do you actually say? Do you want lists
# auto-formatted? Should it preserve profanity, slang, sentence fragments?
# Iterate by running: uv run m0_pipeline.py --file test.wav
CLEANUP_PROMPT = """\
You clean up raw speech-to-text transcripts for dictation. Rules:
- MOST IMPORTANT: when the speaker corrects themselves ("X, actually make
  that Y", "X, no wait, Y", "X, I mean Y"), output only Y. Never keep both
  the correction phrase and the old value.
- Remove filler words (um, uh, like, you know) and false starts.
- Add punctuation, capitalization, and paragraph breaks.
- Preserve the speaker's words and meaning. Do not summarize, expand, shorten,
  or answer questions in the transcript.
- Output ONLY the cleaned text, nothing else.

Example input:
  Um, so the deadline is Tuesday, actually make that Thursday, and, uh, we need like three people on it.
Example output:
  So the deadline is Thursday, and we need three people on it.
"""


def record(seconds: float) -> str:
    """Record from the default mic to a temp wav, return its path."""
    import sounddevice as sd
    import soundfile as sf

    print(f"● Recording {seconds:.0f}s — speak now...", flush=True)
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1)
    sd.wait()
    print("○ Done recording.")
    path = tempfile.mktemp(suffix=".wav")
    sf.write(path, audio, SAMPLE_RATE)
    return path


def transcribe(wav_path: str) -> str:
    from parakeet_mlx import from_pretrained

    t0 = time.perf_counter()
    model = from_pretrained(STT_MODEL)
    load_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    result = model.transcribe(wav_path)
    stt_s = time.perf_counter() - t0

    print(f"  (model load {load_s:.2f}s, transcription {stt_s:.2f}s)")
    return result.text.strip()


def cleanup(raw: str) -> str:
    t0 = time.perf_counter()
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "system": CLEANUP_PROMPT,
            "prompt": raw,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    llm_s = time.perf_counter() - t0
    print(f"  (cleanup {llm_s:.2f}s)")
    return resp.json()["response"].strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--file", help="transcribe this audio file instead of recording")
    ap.add_argument("--raw", action="store_true", help="skip LLM cleanup")
    args = ap.parse_args()

    wav = args.file or record(args.seconds)

    print("\n[1/2] Transcribing (Parakeet TDT 0.6B on MLX)...")
    raw = transcribe(wav)
    print(f"\nRAW TRANSCRIPT:\n  {raw}")

    if args.raw:
        return
    if not raw:
        sys.exit("Nothing transcribed — was the mic silent?")

    print(f"\n[2/2] Cleaning up ({OLLAMA_MODEL} via Ollama)...")
    cleaned = cleanup(raw)
    print(f"\nCLEANED:\n  {cleaned}")


if __name__ == "__main__":
    main()
