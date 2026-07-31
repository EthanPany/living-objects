#!/usr/bin/env python3
"""Offline voice auditioning: batch-generate a short WAV sample per Gemini voice.

Uses the NON-live TTS model (gemini-2.5-flash-preview-tts) so you can listen to
all 30 prebuilt voices in Finder without ever opening the browser app.

Usage:
    python3 preview_voices.py                          # all 30 voices
    python3 preview_voices.py --voices Kore,Puck       # just a couple
    python3 preview_voices.py --text "I am a mug."     # custom line
    python3 preview_voices.py --out /tmp/samples       # custom dir

Requires GEMINI_API_KEY in .env at the project root (or in the environment).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import wave
from pathlib import Path

# --- Local, dependency-free voice catalog -----------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from voices import VOICES, VOICE_BY_NAME  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent

TTS_MODEL = "gemini-2.5-flash-preview-tts"

# Gemini TTS emits raw PCM: signed 16-bit little-endian, mono, 24000 Hz.
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2  # bytes -> 16-bit
CHANNELS = 1

DEFAULT_TEXT = (
    "Hey — yes, down here. I'm the coffee mug you left on the windowsill "
    "three days ago. We should talk about that."
)

# Seconds to wait between requests so a free-tier key doesn't get rate limited.
DEFAULT_DELAY = 1.2


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------
def load_api_key() -> str:
    """Read GEMINI_API_KEY from .env (via python-dotenv) then the environment."""
    env_path = PROJECT_ROOT / ".env"
    try:
        from dotenv import load_dotenv

        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        # python-dotenv missing: fall back to a tiny hand-rolled .env parser.
        if env_path.exists():
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                os.environ.setdefault(key, value)

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print(
            "\nERROR: no GEMINI_API_KEY found.\n\n"
            "  1. cp .env.example .env\n"
            "  2. open .env and paste your key after GEMINI_API_KEY=\n"
            "     (get one at https://aistudio.google.com/apikey)\n"
            "  3. re-run this script\n\n"
            f"Looked for a .env file at: {env_path}\n"
            "You can also just export it:  export GEMINI_API_KEY=...\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------
def extract_pcm(response) -> bytes:
    """Pull raw PCM bytes out of a generate_content response.

    Walks candidates[*].content.parts[*].inline_data.data and concatenates.
    """
    chunks: list[bytes] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in (getattr(content, "parts", None) or []):
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline is not None else None
            if data:
                chunks.append(data)
    if not chunks:
        raise RuntimeError("model returned no audio data")
    return b"".join(chunks)


def write_wav(path: Path, pcm: bytes) -> float:
    """Wrap raw PCM16 in a RIFF/WAV container. Returns duration in seconds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
def synthesize(client, types, text: str, voice: str) -> bytes:
    """One TTS call -> raw PCM16 @ 24kHz mono."""
    response = client.models.generate_content(
        model=TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            ),
        ),
    )
    return extract_pcm(response)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_voice_list(raw: str | None) -> list[str]:
    if not raw:
        return [v["name"] for v in VOICES]

    requested = [name.strip() for name in raw.split(",") if name.strip()]
    # Case-insensitive match against the catalog, but emit canonical casing.
    lowered = {name.lower(): name for name in VOICE_BY_NAME}
    resolved: list[str] = []
    unknown: list[str] = []
    for name in requested:
        canonical = lowered.get(name.lower())
        if canonical:
            resolved.append(canonical)
        else:
            unknown.append(name)

    if unknown:
        print(f"ERROR: unknown voice(s): {', '.join(unknown)}", file=sys.stderr)
        print(
            "Valid voices: " + ", ".join(v["name"] for v in VOICES),
            file=sys.stderr,
        )
        sys.exit(1)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a short WAV sample for each Gemini prebuilt voice.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Line to speak (default: a talkative coffee mug).",
    )
    parser.add_argument(
        "--voices",
        default=None,
        help="Comma-separated voice names, e.g. Kore,Puck (default: all 30).",
    )
    parser.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "voice_samples"),
        help="Output directory (default: ./voice_samples).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Seconds between API calls to dodge rate limits (default: {DEFAULT_DELAY}).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate samples that already exist (default: skip them).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the voice catalog and exit (no API calls, no key needed).",
    )
    args = parser.parse_args()

    if args.list:
        for v in VOICES:
            print(f"{v['name']:<16} {v['character']}")
        print(f"\n{len(VOICES)} voices")
        return 0

    voice_names = parse_voice_list(args.voices)
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    api_key = load_api_key()

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print(
            "ERROR: google-genai is not installed.\n"
            "  pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    client = genai.Client(api_key=api_key)

    print(f"model : {TTS_MODEL}")
    print(f"text  : {args.text}")
    print(f"out   : {out_dir}")
    print(f"voices: {len(voice_names)}\n")

    ok, failed, skipped = 0, 0, 0
    failures: list[tuple[str, str]] = []

    for i, voice in enumerate(voice_names, start=1):
        dest = out_dir / f"{voice}.wav"
        prefix = f"({i}/{len(voice_names)})"

        if dest.exists() and not args.overwrite:
            print(f"{prefix} [skip] {voice} (already exists; --overwrite to redo)")
            skipped += 1
            continue

        try:
            pcm = synthesize(client, types, args.text, voice)
            seconds = write_wav(dest, pcm)
            character = VOICE_BY_NAME.get(voice, {}).get("character", "?")
            print(f"{prefix} [ok] {voice} ({character}, {seconds:.1f}s) -> {dest.name}")
            ok += 1
        except KeyboardInterrupt:
            print("\ninterrupted by user")
            break
        except Exception as e:  # noqa: BLE001 - keep going through all voices
            msg = f"{type(e).__name__}: {e}"
            if len(msg) > 200:
                msg = msg[:200] + "..."
            print(f"{prefix} [fail] {voice}: {msg}")
            failures.append((voice, msg))
            failed += 1

        if i < len(voice_names) and args.delay > 0:
            time.sleep(args.delay)

    print("\n" + "-" * 60)
    print(f"ok: {ok}   failed: {failed}   skipped: {skipped}")
    if failures:
        print("\nfailures:")
        for voice, msg in failures:
            print(f"  {voice}: {msg}")
    print(f"\nsamples in: {out_dir}")
    print(f"open them:  open {out_dir}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
