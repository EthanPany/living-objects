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
Paste it bare — no quotes, no spaces around the `=`.

`.env` is gitignored. Never commit it.

<details>
<summary>If pip refuses with "externally-managed-environment"</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then use `python` in place of `python3` below, and re-run `source .venv/bin/activate` in
each new terminal.
</details>

## Run

```bash
python3 -m uvicorn server:app --port 8000
```

(`uvicorn server:app --port 8000` works too, if `uvicorn` is on your PATH. Add `--reload`
while editing `server.py`.)

Open **http://localhost:8000**, click **Connect**, allow the microphone, and talk.

**Use headphones.** Echo cancellation is enabled, but open speakers next to a hot mic will
still cause the model to hear itself and interrupt mid-sentence.

### Using the lab

- **Mood dropdown 心情** — six temperaments. Picking one rewrites the persona box *and*
  swaps to the voice that carries it. Edit the persona afterwards and the text wins — the
  mood is a starting point, not a lock.

  | Mood | Voice | Register |
  |---|---|---|
  | 高冷 · Weary *(default)* | Algieba | Bored of existence. Nothing is new. Detached, never cruel. |
  | 毒舌 · Dry | Algenib | Deadpan, unimpressed, notices what you'd rather it didn't. |
  | 温柔 · Gentle | Sulafat | Quietly fond of you. Patient. Doesn't fuss. |
  | 阴森 · Ominous | Enceladus | Has seen something. Won't say what. |
  | 哲学 · Philosophical | Charon | Years of nothing but thinking. States conclusions flatly. |
  | 散漫 · Chill | Zubenelgenubi | No ambitions. Nothing has ever been urgent. |

- **Voice dropdown** — all 30 prebuilt voices, listed as `Name — Character` (`Kore — Firm`,
  `Puck — Upbeat`, …). The voice is fixed when the session opens and cannot change mid-call,
  so picking a new one while connected automatically tears the session down and reopens it.
  That's the flicker you see; it takes a moment and clears the conversation history.
- **Persona box** — describe *who the object is*. How it speaks is enforced separately (see below).
  Unlike the voice, persona edits do **not** auto-apply — the hint turns amber to remind you.
- **Apply / Restart** — reopen the session with the current voice and persona.
- **Transcript pane** — live transcription of both sides. `YOU >` is what it actually heard,
  which is the fastest way to tell whether your mic is being understood.
- **Camera 摄像头** — off by default. Tick it and the object can *see*: webcam frames go to
  Gemini at 1 fps, downscaled to 512px, and it will comment on what's in front of it.
  Toggling mid-call reopens the session, same as changing voice. A denied or missing camera
  degrades to audio rather than killing the session.
- **Text box** — send a typed turn without speaking, useful for testing personas quickly.

Mood, voice, and persona are remembered in `localStorage` between reloads.

Turn-taking is deliberately slow: `END_SENSITIVITY_LOW` with a 1200 ms silence window, so it
waits through your pauses instead of pouncing the moment you breathe. Barge-in stays instant
(`START_SENSITIVITY_HIGH`) — you can always cut it off. If it feels *too* patient, drop
`silence_duration_ms` in `server.py`.

## Audition all 30 voices offline

```bash
python3 preview_voices.py
python3 preview_voices.py --text "I have seen things." --voices Algenib,Enceladus,Fenrir
```

Writes `voice_samples/<Voice>.wav` (24 kHz mono PCM16). Select them all in Finder and press
space to arrow through every voice in about a minute.

Files that already exist are skipped, so re-running only fills in what's missing. Other
flags: `--list` (print the catalog, no API key needed), `--overwrite`, `--out <dir>`,
`--delay <seconds>` (default 1.2, spaces out calls to stay under free-tier rate limits).

This uses the standalone TTS model (`gemini-2.5-flash-preview-tts`), not the Live model —
it's for picking a voice, so expect one-shot narration rather than conversational delivery.

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

`BEHAVIOR_RULES` has three parts:

**Content** — brevity and the no-questions rule. Tuning this is a balance, and both ends
fail in ways worth knowing about:

- Too loose ("be brief") and you get 15–26 word replies with a follow-up question every turn.
- Too tight (a hard six-word ceiling plus "let sentences trail off") and it stops speaking
  in sentences at all — output degrades to `just... dust... settling... again...` and it
  starts *refusing* direct requests, because reluctance bleeds from tone into behavior.

The rules now ask for one or two **complete** sentences, and state explicitly that pauses
belong between sentences rather than between words.

**Compliance** — a separate block, because it turned out to be a distinct failure from
verbosity. *Unenthusiastic, not uncooperative.* Asked to sing, count, remember a fact, or
speak a full sentence, it does so on the first request. Sounding put-upon is fine;
withholding is not. A real task overrides the brevity rule — a song gets as many words as
a song needs. It's also told to invent its own lyrics rather than recite an existing song.

**Language** — an explicit English-only lock. Native-audio models choose a language on
their own and will follow you into Chinese mid-conversation. Google's guidance is to pin
the output language in the system instruction, so that's what this does.

**Delivery** — vocal direction, written as notes to a performer. There is no prosody knob
in the API; tone, pace, and accent are steered *through the system instruction*. Specificity
beats adjectives — Google's own example is that "British English as heard in Croydon"
outperforms "British accent" — so this block directs pace, pitch contour, energy, pauses,
and volume separately instead of just saying "sound bored."

### Video

Off by default; tick **Camera** to enable. Frames are captured to an offscreen canvas,
downscaled to 512px on the longest edge, JPEG-encoded at q0.6, and sent as base64 inside
**text** frames — the binary channel stays unambiguously audio, and at 1 fps the ~33%
base64 overhead is noise next to the round trip.

**1 fps is the API ceiling, not a tuning choice.** Don't raise `CAM_FPS`.

That ceiling is convenient rather than limiting: it means a vision model can never drive
a render loop, so the planned motion-pixel canvas stays pure frontend at 60fps while frames
go to Gemini only for semantic understanding. Two independent rates, by design.

Note that audio+video sessions cap at **2 minutes** rather than 15 — which would be fatal
mid-demo, except context window compression is already enabled, so it doesn't apply here.

### Cost

The Live API has **no free tier** — it is paid from the first call, and on the Gemini API
enabling billing removes the free tier from the whole project rather than supplementing it.

| Stream | Rate |
|---|---|
| Audio in | $0.005 / min |
| Audio out | $0.018 / min |
| Video in | $0.002 / min |
| Text in | $0.75 / 1M tokens |

A conversation with camera on runs roughly **$0.025/min (~$1.50/hour)**. Leaving a session
open and forgotten is the thing to watch, not any single call. `preview_voices.py` is 30 TTS
calls at $10/1M audio-output tokens — cents, but not free.

### Not enabled, and why

`enable_affective_dialog` (adapt to the user's emotional tone) and `proactivity`
(let the model decide *not* to answer) both exist on `LiveConnectConfig` — but they require
API version `v1beta` **and** `gemini-2.5-flash-live-preview`. They are not supported on
`gemini-3.1-flash-live-preview`, which is what this uses for its lower latency.

`proactive_audio` is worth the trade for this project specifically: an object whose answer
to a boring remark is *silence* is more alive than one that always replies. Switching means
changing `LIVE_MODEL` and passing `http_options={"api_version": "v1beta"}` to the client.

### WebSocket contract

`ws://localhost:8000/ws`

| Direction | Frame | Payload |
|---|---|---|
| → server | text | `{"type":"config","voice":"Kore","system_instruction":"..."}` (first message) |
| → server | binary | raw PCM16 mono 16000 Hz mic chunks |
| → server | text | `{"type":"text","text":"..."}` — typed turn |
| → server | text | `{"type":"video","data":"<base64 jpeg>"}` — webcam frame, ≤1 fps |
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

Because the Live model is a **preview** model, `server.py` opens the session defensively: it
tries the full config above, and if the model rejects any of those optional tuning fields it
retries once with a minimal config (voice + persona + transcription only) rather than failing
the connection. If you ever see `using minimal live config` in the server log, that's what
happened — the app still works, minus the tuning above.

## Files

| File | Purpose |
|---|---|
| `server.py` | FastAPI WebSocket proxy to Gemini Live |
| `static/index.html` | Self-contained UI — no build step, no dependencies |
| `voices.py` | The 30 prebuilt voices and their characters |
| `preview_voices.py` | Batch-render voice samples to WAV |

---

## Troubleshooting

**`GEMINI_API_KEY is not set`** — there's no `.env`, or it has no key in it.
`cp .env.example .env`, paste your key after `GEMINI_API_KEY=` (no quotes, no spaces around
the `=`), and **restart the server**. Or skip the file entirely and
`export GEMINI_API_KEY=...` before launching uvicorn.

If you instead get **`API key not valid`**, the key exists but is wrong — you reached
Google and it rejected you. Re-copy the whole key from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey); truncation and a stray
trailing newline are the usual culprits.

**Chipmunk (fast/high) or slow-motion (slow/low) audio** — sample rate mismatch. The
contract is strict: **16000 Hz in, 24000 Hz out.** Chipmunk means audio is being played
faster than it was recorded; slow-motion is the reverse.

The usual cause is the browser refusing a 16 kHz capture context and silently handing back
its native rate (44100 or 48000). The app detects this and shows a red banner naming the
rate it actually got — if that banner is up, that's your bug. **Use Chrome**, which honors
`new AudioContext({sampleRate:16000})`; Safari and some Firefox builds don't, and the app
does not resample.

If you've been editing code, check these three agree: `CAPTURE_RATE = 16000` and
`PLAYBACK_RATE = 24000` in `static/index.html`, and `INPUT_MIME = "audio/pcm;rate=16000"`
in `server.py`. The playback `AudioBuffer` must be built at 24000 regardless of what rate
the output context reports.

**It interrupts itself constantly** — it's hearing its own voice through your speakers,
reading that as you barging in, and cutting itself off.

**Put on headphones.** That fixes it instantly and completely.

Without them you're relying on browser acoustic echo cancellation. It's already on
(`echoCancellation: true`, plus `noiseSuppression` and `autoGainControl`, in the
`getUserMedia` constraints in `static/index.html`), but AEC loses to loud speakers, an
external USB mic, or a mic and speaker far apart. Lowering output volume helps. Note that
being interruptible is the *feature* — the bug is only when it interrupts itself with
nobody talking.

**No microphone prompt / `getUserMedia` fails** — browsers only expose the mic on a secure
context: `https://`, or `http://localhost`.

- Open **http://localhost:8000**, not `127.0.0.1:8000`, and never by double-clicking
  `static/index.html` — `file://` has no mic and no working WebSocket.
- If you denied or dismissed the prompt once, the browser remembers. Click the icon at the
  left of the address bar → Site settings → allow Microphone → reload.
- On macOS also check System Settings → Privacy & Security → Microphone and confirm your
  browser is listed and enabled.
- A LAN IP (`http://192.168.x.x:8000`) will **not** get mic access. Use an HTTPS tunnel
  such as ngrok if you need to demo from another machine.

**`Connection closed (code 1006)` / WebSocket error banner** — the server isn't running or
died; check the uvicorn terminal. If the port is taken, run on another one
(`python3 -m uvicorn server:app --port 8001`) and open `http://localhost:8001`.

**Voice dropdown says `(30 · builtin fallback)`** — `GET /voices` failed. Harmless, since
the built-in list is identical, but it usually means the page was opened from `file://`
rather than through the server.

**It answers out loud but the transcript stays empty** — transcription is a separate stream
from the audio and can lag or drop on preview models. If you hear audio, the session is fine.

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
