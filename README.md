# living-objects

Turn any object into a living thing you can talk to.

A voice prototype built on the **Gemini Live API**. You give it a persona and a voice, and
it becomes that object — a fridge, a desk, a 1998 office lamp — and holds a real-time spoken
conversation with you, with interruption, transcription, and unbounded session length.

This repo is the **voice lab**: the backend plumbing plus a browser UI for auditioning all
30 prebuilt voices against different personas until you find the one that sounds alive.

---

## Setup

```bash
git clone https://github.com/EthanPany/living-objects.git
cd living-objects

pip3 install -r requirements.txt

cp .env.example .env
# then edit .env and set GEMINI_API_KEY=<your key>
```

Get a key at **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)**.

`.env` is gitignored. Never commit it.

## Run

```bash
uvicorn server:app --port 8000
```

Open **http://localhost:8000**, click **Connect**, allow the microphone, and talk.

**Use headphones.** Echo cancellation is enabled, but open speakers next to a hot mic will
still cause the model to hear itself and interrupt mid-sentence.

### Using the lab

- **Voice dropdown** — all 30 prebuilt voices. Changing it reopens the session immediately.
- **Persona box** — describe *who the object is*. How it speaks is enforced separately (see below).
- **Apply / Restart** — reopen the session with the current voice and persona.
- **Transcript pane** — live transcription of both sides.
- **Text box** — send a typed turn without speaking, useful for testing personas quickly.

## Audition all 30 voices offline

```bash
python3 preview_voices.py
python3 preview_voices.py --text "I have seen things." --voices Algenib,Enceladus,Fenrir
```

Writes `voice_samples/<Voice>.wav` (24 kHz mono PCM16). Select them all in Finder and press
space to arrow through every voice in about a minute.

Good starting points for inanimate objects: **Algenib** (gravelly), **Enceladus** (breathy),
**Zubenelgenubi** (casual), **Gacrux** (mature), **Fenrir** (excitable).

---

## How it works

```
browser  ──mic PCM16 @16kHz──▶  server.py  ──▶  Gemini Live API
   ▲                                                   │
   └────────audio PCM16 @24kHz + transcripts───────────┘
```

`server.py` is a thin WebSocket proxy. The browser never sees your API key.

**Sample rates are not interchangeable** — 16 kHz in, 24 kHz out. Mismatching them is the
single most common bug and produces chipmunk or slow-motion audio.

### Persona vs. behavior

The persona says *who the object is*. `BEHAVIOR_RULES` in `server.py` is appended to every
persona and governs *how it speaks* — short replies, no interrogation, no offers of help,
never breaking character as an AI.

This split exists because it's load-bearing. Without those rules the model reverts to
assistant habits: paragraph-length answers and a follow-up question every single turn. That
reads as a chatbot in a costume rather than a thing that happens to be alive. Rewrite the
persona freely; the behavior rules keep applying.

### WebSocket contract

`ws://localhost:8000/ws`

| Direction | Frame | Payload |
|---|---|---|
| → server | text | `{"type":"config","voice":"Kore","system_instruction":"..."}` (first message) |
| → server | binary | raw PCM16 mono 16000 Hz mic chunks |
| → server | text | `{"type":"text","text":"..."}` — typed turn |
| ← client | text | `{"type":"ready","voice":str}` |
| ← client | binary | raw PCM16 mono 24000 Hz playback audio |
| ← client | text | `{"type":"interrupted"}` — flush the playback queue |
| ← client | text | `{"type":"turn_complete"}` |
| ← client | text | `{"type":"transcript","role":"user"\|"model","text":str}` |
| ← client | text | `{"type":"error","message":str}` |

### Notable configuration

- **Context window compression** — without it, audio sessions hard-cap at 15 minutes
  (2 minutes with video). With it, sessions are effectively unbounded.
- **`START_OF_ACTIVITY_INTERRUPTS`** — barge-in. Talking over the model stops it instantly.
- **Input + output transcription** — both sides of the conversation as text.
- **Session resumption** — survives transient disconnects.

## Files

| File | Purpose |
|---|---|
| `server.py` | FastAPI WebSocket proxy to Gemini Live |
| `static/index.html` | Self-contained UI — no build step, no dependencies |
| `voices.py` | The 30 prebuilt voices and their characters |
| `preview_voices.py` | Batch-render voice samples to WAV |

---

## Troubleshooting

**`GEMINI_API_KEY is not set`** — `cp .env.example .env`, add your key, restart the server.

**Chipmunk or slow-motion audio** — sample rate mismatch. Capture must be 16000 Hz, playback
24000 Hz.

**It interrupts itself constantly** — it's hearing its own voice. Use headphones. Confirm
`echoCancellation: true` in the `getUserMedia` constraints.

**No microphone prompt** — mic access requires a secure origin. `localhost` qualifies; a LAN
IP does not. Use `localhost`, not `127.0.0.1:8000` via another machine.

**It won't stop asking questions** — your persona is probably overriding `BEHAVIOR_RULES`.
Remove any instruction to be curious or ask questions from the persona box.

**Replies are too long** — strengthen `BEHAVIOR_RULES` in `server.py`; it's appended to
every session.

## Roadmap

The voice layer is the foundation. What's planned on top:

- Full-screen 1-bit dithered canvas — webcam motion rendered as decaying white pixels
- A Macintosh-style face whose eyes track the motion centroid and whose mouth follows audio
- Audio-reactive pixels growing inward from the screen edge by intensity
- Photo → persona bootstrap: point a camera at an object, it becomes that object
- Persistent memory and an episodic log, so the object remembers what it saw from where it sits
