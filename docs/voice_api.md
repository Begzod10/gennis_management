# Voice Mission API

Three endpoints for creating missions via voice. Choose the one that fits your use case.

---

## 1. One-Shot Upload — `POST /api/v1/voice-missions/transcribe`

Upload a pre-recorded audio file. Returns a list of proposed missions with suggested executors. The manager reviews the proposals and confirms by calling `POST /api/v1/missions/` separately.

### Request

**Content-Type:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `audio` | file | ✅ | Audio file (mp3, mp4, m4a, wav, webm, ogg, flac). Max 25 MB. |
| `creator_id` | int (query) | ✅ | ID of the user sending the voice message. |
| `top_k` | int (query) | ❌ | Max executor suggestions per proposal. Default `3`, max `10`. |

**Example request (curl):**
```bash
curl -X POST "https://office.gennis.uz/api/v1/voice-missions/transcribe?creator_id=5&top_k=3" \
  -F "audio=@voice_note.mp3"
```

### Response `200 OK`

```json
{
  "transcript": "Ali Karimovga holodilnik ta'mirlashni topshiring, 2 kun ichida.",
  "proposals": [
    {
      "title": "Holodilnik ta'mirlash",
      "description": "Ali Karimovga holodilnik ta'mirlash vazifasi berildi.",
      "deadline": "2026-06-26",
      "deadline_days": 2,
      "category": "maintenance",
      "executor_role_hint": "technician",
      "raw_excerpt": "Ali Karimovga holodilnik ta'mirlashni topshiring, 2 kun ichida.",
      "executor_suggestions": [
        {
          "user_id": 12,
          "name": "Ali Karimov",
          "role": "employee",
          "job": "Texnik",
          "score": 0.94,
          "reason": "Ali Karimov's job title 'Texnik' directly matches the maintenance task."
        },
        {
          "user_id": 8,
          "name": "Sardor Rahimov",
          "role": "employee",
          "job": "Texnik",
          "score": 0.71,
          "reason": "Past missions include 'Konditsioner ta'mirlash', relevant maintenance experience."
        }
      ]
    }
  ]
}
```

### Error responses

| Code | Reason |
|---|---|
| `404` | `creator_id` not found |
| `413` | Audio file exceeds 25 MB |
| `422` | Unsupported audio format or empty file |
| `502` | Whisper / GPT API call failed |

---

## 2. OpenAI Realtime Voice Chat — `WebSocket /api/v1/voice-realtime/ws`

True bidirectional voice chat powered by **GPT-4o Realtime API**. The AI converses naturally, asks clarifying questions, and creates missions directly in the database.

### Connection

```
ws://your-server/api/v1/voice-realtime/ws?creator_id=5
```

| Query param | Required | Description |
|---|---|---|
| `creator_id` | ✅ | ID of the manager speaking. |

**Audio format (input):** PCM-16, **24 000 Hz**, mono, little-endian  
**Audio format (output):** PCM-16, **24 000 Hz**, mono, little-endian

---

### Client → Server messages

#### Binary — audio chunk
Send raw PCM-16 audio bytes continuously while recording.

```
[binary frame: raw PCM-16 bytes at 24kHz]
```

#### Text JSON — control messages

```json
{ "type": "commit" }
```
Force end of your speech turn (optional — server VAD handles this automatically).

```json
{ "type": "interrupt" }
```
Cancel the AI's current response.

---

### Server → Client messages

#### Binary — AI voice audio
Raw PCM-16 bytes at 24kHz. Play directly to the speaker.

```
[binary frame: raw PCM-16 bytes at 24kHz]
```

#### Text JSON — events

**`session_ready`** — connection established, start sending audio.
```json
{ "type": "session_ready" }
```

**`user_speech_started`** — VAD detected the user started speaking.
```json
{ "type": "user_speech_started" }
```

**`user_speech_stopped`** — VAD detected the user stopped speaking.
```json
{ "type": "user_speech_stopped" }
```

**`user_transcript`** — Whisper transcription of what the manager said.
```json
{
  "type": "user_transcript",
  "text": "Sardor Toshmatovga hisobot tayyorlash topshirig'ini bering, 3 kun muhlat"
}
```

**`ai_transcript`** — What the AI is saying (streams word by word).
```json
{
  "type": "ai_transcript",
  "text": "Sardor Toshmatov — hisobot tayyorlash,"
}
```

**`mission_created`** — A mission was successfully created in the database.
```json
{
  "type": "mission_created",
  "mission_id": 84,
  "title": "Hisobot tayyorlash",
  "executor": "Sardor Toshmatov",
  "deadline": "2026-06-27"
}
```

**`error`** — Something went wrong.
```json
{
  "type": "error",
  "message": "OpenAI connection closed"
}
```

---

### Example browser session (JavaScript)

```javascript
const ws = new WebSocket('wss://office.gennis.uz/api/v1/voice-realtime/ws?creator_id=5');

ws.onopen = () => console.log('connected');

ws.onmessage = (event) => {
  if (event.data instanceof Blob) {
    // AI voice audio — play it
    playAudio(event.data);
  } else {
    const msg = JSON.parse(event.data);

    if (msg.type === 'session_ready') startRecording(); // begin sending audio
    if (msg.type === 'user_transcript') showUserText(msg.text);
    if (msg.type === 'ai_transcript')   showAIText(msg.text);
    if (msg.type === 'mission_created') showMissionBadge(msg);
  }
};

// Send raw PCM-16 audio at 24kHz from microphone
mediaRecorder.ondataavailable = (e) => ws.send(e.data);
```

---

## 3. Gemini Live Voice Chat — `WebSocket /api/v1/gemini-voice/ws`

Same conversation experience as the OpenAI version but powered by **Gemini 2.0 Flash Live** — better Uzbek and Russian language understanding.

### Connection

```
ws://your-server/api/v1/gemini-voice/ws?creator_id=5
```

**Audio format (input):** PCM-16, **16 000 Hz**, mono, little-endian ⚠️ different from OpenAI  
**Audio format (output):** PCM-16, **24 000 Hz**, mono, little-endian

---

### Client → Server messages

Same as the OpenAI version, but input audio must be **16kHz** (not 24kHz).

#### Binary — audio chunk
```
[binary frame: raw PCM-16 bytes at 16kHz]
```

#### Text JSON — control
```json
{ "type": "interrupt" }
```

---

### Server → Client messages

Identical event schema to the OpenAI version. The `session_ready` event tells the client the sample rates:

```json
{
  "type": "session_ready",
  "input_sample_rate": 16000,
  "output_sample_rate": 24000
}
```

All other events (`user_transcript`, `ai_transcript`, `mission_created`, `error`) are identical to the OpenAI version.

---

### Example browser session (JavaScript)

```javascript
const ws = new WebSocket('wss://office.gennis.uz/api/v1/gemini-voice/ws?creator_id=5');

ws.onmessage = (event) => {
  if (event.data instanceof Blob) {
    playAudio(event.data);  // 24kHz PCM output
  } else {
    const msg = JSON.parse(event.data);

    if (msg.type === 'session_ready') {
      // Use msg.input_sample_rate (16000) to configure your recorder
      startRecording({ sampleRate: msg.input_sample_rate });
    }
    if (msg.type === 'mission_created') showMissionBadge(msg);
  }
};
```

---

## Comparison

| Feature | Upload (`/transcribe`) | OpenAI Realtime | Gemini Live |
|---|---|---|---|
| Interaction | One-shot upload | Live conversation | Live conversation |
| Uzbek quality | Good (Whisper) | Good | **Best** |
| Input audio | File upload | PCM-16 @ 24kHz | PCM-16 @ **16kHz** |
| Output audio | None (text only) | PCM-16 @ 24kHz | PCM-16 @ 24kHz |
| Mission creation | Manual (confirm step) | Automatic | Automatic |
| Config key | `OPENAI_API_KEY` | `OPENAI_API_KEY` | `GEMINI_API_KEY` |

---

## Available functions (AI tools)

The AI in both realtime endpoints can call these functions automatically:

### `list_executors`
Returns all active management users.

**Sample response to AI:**
```json
{
  "executors": [
    { "id": 5,  "name": "Ali Karimov",    "role": "employee", "job": "Texnik" },
    { "id": 12, "name": "Sardor Rahimov", "role": "employee", "job": "Dasturchi" }
  ]
}
```

### `search_executor_by_name`
Fuzzy name search — triggered when the manager mentions a person by name.

**Input:** `{ "name": "Sardor" }`

**Sample response to AI:**
```json
{
  "executors": [
    { "id": 12, "name": "Sardor Rahimov", "role": "employee", "job": "Dasturchi" }
  ]
}
```

### `create_mission`
Creates the mission in the management database.

**Input:**
```json
{
  "title": "Hisobot tayyorlash",
  "description": "Oylik moliyaviy hisobot tayyorlansin",
  "executor_id": 12,
  "creator_id": 5,
  "deadline_days": 3,
  "category": "report"
}
```

**Sample response to AI:**
```json
{
  "success": true,
  "mission_id": 84,
  "title": "Hisobot tayyorlash",
  "executor": "Sardor Rahimov",
  "deadline": "2026-06-27",
  "category": "report"
}
```

---

## Environment variables

```env
# OpenAI (used by /transcribe and /voice-realtime)
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_WHISPER_MODEL=whisper-1
OPENAI_REALTIME_URL=wss://api.openai.com/v1/realtime
OPENAI_REALTIME_MODEL=gpt-4o-realtime-preview

# Gemini (used by /gemini-voice)
GEMINI_API_KEY=AQ...
GEMINI_REALTIME_MODEL=models/gemini-2.0-flash-live-001
GEMINI_VOICE=Aoede   # options: Puck, Charon, Kore, Fenrir, Aoede, Orbit, Zephyr
```
