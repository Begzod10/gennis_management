"""OpenAI Realtime API voice chat — WebSocket proxy.

The browser connects to:
    ws://.../api/v1/voice-realtime/ws?creator_id=<id>

The backend then opens a WebSocket to OpenAI's Realtime API and bridges them.

Client → Server messages:
  binary  : raw PCM-16 audio (24 000 Hz mono, little-endian)
  text JSON: {"type": "commit"} — force end of speech turn (optional)
             {"type": "interrupt"} — cancel current AI response

Server → Client messages:
  binary  : raw PCM-16 audio from the AI voice response
  text JSON events:
    {"type": "session_ready"}
    {"type": "user_speech_started"}
    {"type": "user_speech_stopped"}
    {"type": "user_transcript", "text": "..."}
    {"type": "ai_transcript", "text": "..."}
    {"type": "mission_created", "mission_id": 42, "title": "...", "executor": "...", "deadline": "..."}
    {"type": "error", "message": "..."}
    {"type": "done"}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Optional

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.services.realtime_session import (
    build_session_update,
    build_uzbek_primer,
    dispatch_function_call,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice-realtime", tags=["voice-realtime"])

_OPENAI_EXTRA_HEADERS: dict = {}


async def _send_json(ws, data: dict):
    await ws.send(json.dumps(data))


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws")
async def voice_realtime_ws(
    websocket: WebSocket,
    creator_id: int = Query(..., description="ID of the user starting the voice session"),
):
    """
    Bidirectional voice chat proxy to OpenAI Realtime API.

    The client sends raw PCM-16 audio, receives PCM-16 audio back from the AI.
    Function calls (create_mission, list_executors, etc.) are executed server-side
    against the management database.
    """
    if not settings.OPENAI_API_KEY:
        await websocket.close(code=1008, reason="OPENAI_API_KEY not configured")
        return

    await websocket.accept()

    # Validate creator
    # We open our own DB session because WebSocket endpoints can't use Depends(get_db)
    # with the normal generator pattern — we manage it manually.
    from app.database import SessionLocal
    db: Session = SessionLocal()
    try:
        creator = db.query(User).filter(User.id == creator_id, User.deleted == False).first()
        if not creator:
            await _send_client_json(websocket, {"type": "error", "message": "Creator not found"})
            await websocket.close(code=1008)
            return
    except Exception as exc:
        logger.error("DB error validating creator %s: %s", creator_id, exc)
        await websocket.close(code=1011)
        db.close()
        return

    realtime_url = (
        f"{settings.OPENAI_REALTIME_URL}?model={settings.OPENAI_REALTIME_MODEL}"
    )
    openai_headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        **_OPENAI_EXTRA_HEADERS,
    }

    try:
        async with websockets.connect(
            realtime_url,
            additional_headers=openai_headers,
            ping_interval=20,
            ping_timeout=20,
        ) as openai_ws:

            # Send session configuration
            creator_name = f"{creator.name} {creator.surname or ''}".strip()
            session_msg = build_session_update(creator_name)
            logger.info("Sending session.update: %s", json.dumps(session_msg))
            await openai_ws.send(json.dumps(session_msg))

            # Inject an Uzbek assistant message to lock the response language
            await openai_ws.send(json.dumps(build_uzbek_primer()))

            await _send_client_json(websocket, {"type": "session_ready"})

            # Run both directions concurrently; stop when either side disconnects
            client_task = asyncio.create_task(
                _client_to_openai(websocket, openai_ws)
            )
            openai_task = asyncio.create_task(
                _openai_to_client(websocket, openai_ws, db, creator_id)
            )

            done, pending = await asyncio.wait(
                [client_task, openai_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    except WebSocketDisconnect:
        pass
    except websockets.exceptions.InvalidStatusCode as exc:
        detail = f"OpenAI rejected connection: HTTP {exc.status_code}"
        logger.error("OpenAI Realtime handshake failed (creator=%s): %s", creator_id, exc)
        await _send_client_json(websocket, {"type": "error", "message": detail})
    except websockets.exceptions.ConnectionClosedError as exc:
        logger.warning("OpenAI Realtime WS closed (creator=%s): %s", creator_id, exc)
        await _send_client_json(websocket, {
            "type": "error",
            "message": f"OpenAI connection closed: code={exc.code} reason={exc.reason}",
        })
    except Exception as exc:
        logger.error("Realtime session error (creator=%s): %s", creator_id, exc)
        await _send_client_json(websocket, {"type": "error", "message": str(exc)})
    finally:
        db.close()
        try:
            await websocket.close()
        except Exception:
            pass


# ── Client → OpenAI ───────────────────────────────────────────────────────────

async def _client_to_openai(client_ws: WebSocket, openai_ws) -> None:
    """Forward audio and control messages from the browser to OpenAI.

    The proxy has built-in server VAD (we see speech_started/stopped/committed
    events), so we just stream audio and let the proxy handle turn detection.
    """
    try:
        while True:
            msg = await client_ws.receive()

            if "bytes" in msg and msg["bytes"]:
                audio_b64 = base64.b64encode(msg["bytes"]).decode()
                await openai_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": audio_b64,
                }))

            elif "text" in msg and msg["text"]:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "commit":
                    await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    await openai_ws.send(json.dumps({"type": "response.create"}))
                elif data.get("type") == "interrupt":
                    await openai_ws.send(json.dumps({"type": "response.cancel"}))

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("client_to_openai stopped: %s", exc)


# ── OpenAI → Client ───────────────────────────────────────────────────────────

async def _openai_to_client(client_ws: WebSocket, openai_ws, db: Session, creator_id: int) -> None:
    """Forward OpenAI events to the browser; handle function calls server-side."""
    # Accumulate streaming function call arguments
    pending_calls: dict[str, dict] = {}  # call_id → {name, args_buf}

    try:
        async for raw in openai_ws:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")
            logger.warning("OpenAI event: %s | %s", etype, json.dumps(event)[:300])

            # ── Voice activity detection ──────────────────────────────────────
            if etype == "input_audio_buffer.speech_started":
                await _send_client_json(client_ws, {"type": "user_speech_started"})

            elif etype == "input_audio_buffer.speech_stopped":
                await _send_client_json(client_ws, {"type": "user_speech_stopped"})

            # ── User transcript (Whisper result) ─────────────────────────────
            elif etype == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "")
                if transcript:
                    await _send_client_json(client_ws, {
                        "type": "user_transcript",
                        "text": transcript,
                    })

            # ── AI transcript (what the AI is saying) ────────────────────────
            elif etype in ("response.audio_transcript.delta", "response.output_audio_transcript.delta"):
                delta = event.get("delta", "")
                if delta:
                    await _send_client_json(client_ws, {
                        "type": "ai_transcript",
                        "text": delta,
                    })

            # ── AI voice audio ────────────────────────────────────────────────
            elif etype in ("response.audio.delta", "response.output_audio.delta"):
                audio_b64 = event.get("delta", "")
                if audio_b64:
                    try:
                        audio_bytes = base64.b64decode(audio_b64)
                        await client_ws.send_bytes(audio_bytes)
                    except Exception:
                        pass

            # ── Function call streaming ───────────────────────────────────────
            elif etype == "response.output_item.added":
                item = event.get("item", {})
                if item.get("type") == "function_call":
                    call_id = item.get("call_id") or item.get("id", "")
                    pending_calls[call_id] = {"name": item.get("name", ""), "args_buf": ""}

            elif etype == "response.function_call_arguments.delta":
                call_id = event.get("call_id", "")
                if call_id in pending_calls:
                    pending_calls[call_id]["args_buf"] += event.get("delta", "")

            elif etype == "response.function_call_arguments.done":
                call_id = event.get("call_id", "")
                fn_name = event.get("name", "") or (pending_calls.get(call_id, {}).get("name", ""))
                args_str = event.get("arguments", "") or (pending_calls.get(call_id, {}).get("args_buf", ""))

                if fn_name:
                    result = dispatch_function_call(fn_name, args_str, db, creator_id)

                    # If a mission was created, notify the client
                    if fn_name == "create_mission":
                        try:
                            r = json.loads(result)
                            if r.get("success"):
                                await _send_client_json(client_ws, {
                                    "type": "mission_created",
                                    "mission_id": r.get("mission_id"),
                                    "title": r.get("title"),
                                    "executor": r.get("executor"),
                                    "deadline": r.get("deadline"),
                                })
                        except Exception:
                            pass

                    # Send result back to OpenAI so it can continue the conversation
                    await openai_ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result,
                        },
                    }))
                    await openai_ws.send(json.dumps({"type": "response.create"}))

                pending_calls.pop(call_id, None)

            # ── Response failed (e.g. rate_limit_exceeded) ────────────────────
            elif etype == "response.done":
                resp = event.get("response", {})
                if resp.get("status") == "failed":
                    err = (resp.get("status_details") or {}).get("error", {})
                    code = err.get("code", "")
                    msg = err.get("message", "Response failed")
                    logger.warning("OpenAI response failed: code=%s msg=%s", code, msg)
                    if code == "rate_limit_exceeded":
                        await _send_client_json(client_ws, {
                            "type": "error",
                            "message": "Rate limit reached — please wait a moment and try again.",
                        })
                    else:
                        await _send_client_json(client_ws, {"type": "error", "message": msg})

            # ── Errors ────────────────────────────────────────────────────────
            elif etype == "error":
                err = event.get("error", {})
                msg = err.get("message", "Unknown OpenAI error")
                logger.warning("OpenAI Realtime error (full): %s", json.dumps(event))
                await _send_client_json(client_ws, {"type": "error", "message": msg})

    except websockets.exceptions.ConnectionClosed:
        pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("openai_to_client stopped: %s", exc)


# ── Helper ────────────────────────────────────────────────────────────────────

async def _send_client_json(ws: WebSocket, data: dict) -> None:
    try:
        await ws.send_text(json.dumps(data))
    except Exception:
        pass
