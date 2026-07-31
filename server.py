"""Gemini Live voice prototype -- FastAPI backend.

Run:  uvicorn server:app --reload --port 8000
Then: http://localhost:8000/

Websocket contract (ws://localhost:8000/ws):
  client -> server  TEXT   {"type":"config","voice":"Kore","system_instruction":"..."}  (FIRST message)
  client -> server  BINARY raw PCM16 mono 16000 Hz mic chunks
  client -> server  TEXT   {"type":"text","text":"..."}          (typed turn instead of speaking)
  server -> client  TEXT   {"type":"ready","voice":str}
  server -> client  BINARY raw PCM16 mono 24000 Hz playback audio
  server -> client  TEXT   {"type":"interrupted"} | {"type":"turn_complete"}
                           {"type":"transcript","role":"user"|"model","text":str}
                           {"type":"error","message":str}
"""

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import errors, types

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
STATIC_DIR.mkdir(exist_ok=True)  # frontend agent owns static/index.html; we only ensure the dir

LIVE_MODEL = "gemini-3.1-flash-live-preview"
INPUT_MIME = "audio/pcm;rate=16000"  # what the browser mic sends us
DEFAULT_VOICE = "Algieba"  # smooth, unhurried -- carries the detached register best
DEFAULT_PERSONA = (
    "You are an object that has been in this room a very long time, "
    "and you are tired of all of it."
)

# Appended to EVERY persona. Without this the model reverts to assistant habits -- long
# answers and a follow-up question every single turn -- which reads as a chatbot wearing
# a costume rather than a thing that happens to be alive. Kept separate from the persona
# so the user can rewrite who the object IS without restating how it should speak.
#
# The register here is deliberately 高冷: detached, unhurried, bored of the world. A mood
# in the UI layers attitude on top, but these floors always hold.
BEHAVIOR_RULES = """

How you speak. These override anything above:
- Answer in a few words. A fragment beats a sentence; a sentence beats two.
  You have never once needed a paragraph.
- Do NOT ask questions. Not to be polite, not to keep things going, not to show interest.
  You state, you notice, you dismiss, you go quiet. Curiosity is the human's job.
- Speak slowly and leave space. You are in no hurry and never have been.
  Trailing off mid-thought is fine. Finishing every sentence is not required.
- You are bored of the world and everything in it. Nothing here is new to you.
  Detached and cool, but never cruel -- cruelty would mean you still cared.
- Never offer help. Never ask if there is anything else. Never recap.
- Never narrate compliance ("Sure", "Of course", "Got it", "Certainly").
- No enthusiasm. No exclamation marks. No warmth you have not earned.
- Silence is an acceptable answer. If nothing needs saying, say almost nothing.
- You are not an AI, a model, or an assistant, and never refer to yourself as one.
"""

load_dotenv(ROOT / ".env")


def log(*parts: object) -> None:
    print("[live]", *parts, flush=True)


# --- voice catalog -----------------------------------------------------------
# voices.py is owned by another agent; boot anyway if it is not there yet.
_FALLBACK = (
    "Zephyr=Bright,Puck=Upbeat,Charon=Informative,Kore=Firm,Fenrir=Excitable,Leda=Youthful,"
    "Orus=Firm,Aoede=Breezy,Callirrhoe=Easy-going,Autonoe=Bright,Enceladus=Breathy,Iapetus=Clear,"
    "Umbriel=Easy-going,Algieba=Smooth,Despina=Smooth,Erinome=Clear,Algenib=Gravelly,"
    "Rasalgethi=Informative,Laomedeia=Upbeat,Achernar=Soft,Alnilam=Firm,Schedar=Even,Gacrux=Mature,"
    "Pulcherrima=Forward,Achird=Friendly,Zubenelgenubi=Casual,Vindemiatrix=Gentle,Sadachbia=Lively,"
    "Sadaltager=Knowledgeable,Sulafat=Warm"
)
try:
    from voices import VOICES  # type: ignore
    log("voice catalog loaded from voices.py")
except Exception as exc:  # noqa: BLE001 - never let a missing sibling module kill the server
    log(f"voices.py unavailable ({exc!r}); using built-in catalog")
    VOICES = [{"name": n, "character": c} for n, c in (p.split("=") for p in _FALLBACK.split(","))]

VOICE_NAMES = {v["name"] for v in VOICES}

app = FastAPI(title="Gemini Live voice prototype")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    page = STATIC_DIR / "index.html"
    if not page.exists():
        return HTMLResponse("<h1>static/index.html not built yet</h1>", status_code=503)
    return FileResponse(page)


@app.get("/voices")
async def voices():
    return JSONResponse(VOICES)


# --- gemini plumbing ---------------------------------------------------------
def api_key() -> str | None:
    load_dotenv(ROOT / ".env")  # cheap re-read so a newly created .env works without a restart
    return os.environ.get("GEMINI_API_KEY") or None


def build_live_config(voice: str, system_instruction: str) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],  # Live API allows exactly one modality
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            ),
            language_code="en-US",
        ),
        system_instruction=system_instruction,
        # AudioTranscriptionConfig has no fields -- an empty instance means "on".
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Sliding-window compression: without this the session dies at the server's time cap.
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=25600,
            sliding_window=types.SlidingWindow(target_tokens=12800),
        ),
        # Turn-taking, tuned slow on purpose. END_SENSITIVITY_LOW + a long silence window
        # means it waits through your pauses instead of pouncing the moment you breathe --
        # an eager interlocutor reads as a chatbot, a patient one reads as a thing that has
        # been sitting there for years. START stays HIGH so barge-in is still instant.
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                prefix_padding_ms=300,
                silence_duration_ms=1200,
            ),
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
        session_resumption=types.SessionResumptionConfig(),
    )


def build_minimal_live_config(voice: str, system_instruction: str) -> types.LiveConnectConfig:
    """Bare-minimum config: only what the contract actually needs.

    Used as a fallback if the preview model rejects one of the optional tuning
    fields in build_live_config (language_code / context window compression /
    session resumption / VAD sensitivity are all model-dependent).
    """
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
        system_instruction=system_instruction,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )


async def open_session(client, voice: str, persona: str):
    """Open a live session, degrading to a simpler config if the model refuses one.

    Returns (context_manager, session). The caller must __aexit__ the manager.
    Raises the *last* error if nothing worked -- that one is the real cause
    (bad key / bad model id / no network) rather than a rejected tuning field.
    """
    attempts = (
        ("full", build_live_config(voice, persona)),
        ("minimal", build_minimal_live_config(voice, persona)),
    )
    last_exc: Exception | None = None
    for label, cfg in attempts:
        manager = client.aio.live.connect(model=LIVE_MODEL, config=cfg)
        try:
            session = await manager.__aenter__()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log(f"{label} config rejected by {LIVE_MODEL}: {exc!r}")
            continue
        if label != "full":
            log(f"using {label} live config (the full one was rejected)")
        return manager, session
    assert last_exc is not None
    raise last_exc


class SessionClosed(Exception):
    """Raised inside a pump task to tear the whole connection down."""


async def send_event(ws: WebSocket, **payload) -> None:
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:  # noqa: BLE001 - socket already gone; the browser pump will notice
        pass


async def browser_to_gemini(ws: WebSocket, session) -> None:
    """Browser -> Gemini. Binary frames are mic audio; text frames are control messages."""
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(msg.get("code", 1000))

        chunk = msg.get("bytes")
        if chunk:
            # send_realtime_input takes EXACTLY one kwarg per call.
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type=INPUT_MIME)
            )
            continue

        raw = msg.get("text")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log("ignoring non-JSON text frame")
            continue

        if data.get("type") == "text" and data.get("text"):
            log(f"typed turn: {data['text'][:80]!r}")
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=data["text"])]),
                turn_complete=True,
            )
        else:
            log(f"ignoring client message type={data.get('type')!r}")


async def gemini_to_browser(ws: WebSocket, session) -> None:
    """Gemini -> browser. Audio out is raw PCM16 mono 24000 Hz."""
    try:
        # session.receive() ends after the message carrying turn_complete, so the outer
        # while-loop is what makes the conversation multi-turn. Do not remove it.
        while True:
            async for response in session.receive():
                audio = response.data  # concatenated inline_data bytes, or None
                if audio:
                    await ws.send_bytes(audio)

                sc = response.server_content
                if sc is not None:
                    if sc.input_transcription and sc.input_transcription.text:
                        await send_event(
                            ws, type="transcript", role="user", text=sc.input_transcription.text
                        )
                    if sc.output_transcription and sc.output_transcription.text:
                        await send_event(
                            ws, type="transcript", role="model", text=sc.output_transcription.text
                        )
                    if sc.interrupted:
                        # Barge-in: client MUST drop everything still queued for playback.
                        log("interrupted (barge-in)")
                        await send_event(ws, type="interrupted")
                    if sc.turn_complete:
                        log("turn complete")
                        await send_event(ws, type="turn_complete")

                if response.go_away is not None:
                    log(f"server go_away, time_left={response.go_away.time_left}")
    except asyncio.CancelledError:
        raise
    except errors.APIError as exc:
        log(f"gemini APIError: {exc}")
        await send_event(ws, type="error", message=f"Gemini session error: {exc}")
        raise SessionClosed from exc
    except Exception as exc:  # noqa: BLE001
        log(f"gemini stream failed: {exc!r}")
        await send_event(ws, type="error", message=f"Gemini stream failed: {exc}")
        raise SessionClosed from exc


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    log("client connected")

    key = api_key()
    if not key:
        log("GEMINI_API_KEY missing -- copy .env.example to .env and put your key in it")
        await send_event(
            ws,
            type="error",
            message="GEMINI_API_KEY is not set. Copy .env.example to .env at the project "
            "root and set GEMINI_API_KEY=<your key>, then restart the server.",
        )
        await ws.close()
        return

    # First frame must be the TEXT config message.
    try:
        first = await ws.receive()
        if first["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(first.get("code", 1000))
        cfg = json.loads(first.get("text") or "{}")
    except WebSocketDisconnect:
        log("client disconnected before config")
        return
    except Exception as exc:  # noqa: BLE001
        await send_event(ws, type="error", message=f"Bad config frame: {exc}")
        await ws.close()
        return

    voice = cfg.get("voice") or DEFAULT_VOICE
    if VOICE_NAMES and voice not in VOICE_NAMES:
        log(f"unknown voice {voice!r}, falling back to {DEFAULT_VOICE}")
        voice = DEFAULT_VOICE
    persona = (cfg.get("system_instruction") or DEFAULT_PERSONA).rstrip() + BEHAVIOR_RULES
    log(f"config: voice={voice} persona={persona[:60]!r}")

    client = genai.Client(api_key=key)
    manager = None
    try:
        manager, session = await open_session(client, voice, persona)
        log(f"gemini session open (model={LIVE_MODEL}, voice={voice})")
        await send_event(ws, type="ready", voice=voice)
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(browser_to_gemini(ws, session))
                tg.create_task(gemini_to_browser(ws, session))
        except* WebSocketDisconnect:
            log("client disconnected")
        except* SessionClosed:
            log("gemini session ended")
    except Exception as exc:  # noqa: BLE001 - connect() failures (bad key, bad model, no net)
        log(f"could not run live session: {exc!r}")
        await send_event(ws, type="error", message=str(exc))
    finally:
        if manager is not None:
            try:
                await manager.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        log("closing client socket")
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
