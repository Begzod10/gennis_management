"""Gemini Live API voice chat — WebSocket proxy.

The browser connects to:
    ws://.../api/v1/gemini-voice/ws?creator_id=<id>

Audio format (IMPORTANT — different from OpenAI version):
  Client → Server : raw PCM-16, 16 000 Hz mono (16kHz)
  Server → Client : raw PCM-16, 24 000 Hz mono (24kHz)

Client → Server messages:
  binary  : raw PCM-16 audio at 16kHz
  text JSON: {"type": "interrupt"} — cancel current AI response

Server → Client messages:
  binary  : raw PCM-16 audio at 24kHz (AI voice)
  text JSON events (same schema as OpenAI version for frontend compatibility):
    {"type": "session_ready", "input_sample_rate": 16000, "output_sample_rate": 24000}
    {"type": "user_speech_started"}
    {"type": "user_speech_stopped"}
    {"type": "user_transcript", "text": "..."}
    {"type": "ai_transcript", "text": "..."}
    {"type": "mission_created", "mission_id": 42, "title": "...", "executor": "...", "deadline": "..."}
    {"type": "error", "message": "..."}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.services.gemini_realtime_session import build_setup_message
from app.services.realtime_session import dispatch_function_call

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gemini-voice", tags=["gemini-voice"])

_GEMINI_WS_BASE = (
    "wss://generativelanguage.googleapis.com"
    "/ws/google.ai.generativelanguage.v1alpha"
    ".GenerativeService.BidiGenerateContent"
)


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws")
async def gemini_voice_ws(
    websocket: WebSocket,
    creator_id: int = Query(..., description="ID of the user starting the voice session"),
):
    """
    Bidirectional voice chat proxy to Google Gemini Live API.

    Client sends raw 16kHz PCM-16 audio, receives 24kHz PCM-16 AI voice back.
    Function calls are executed server-side against the management database.
    """
    if not settings.GEMINI_API_KEY:
        await websocket.close(code=1008, reason="GEMINI_API_KEY not configured")
        return

    await websocket.accept()

    db = SessionLocal()
    try:
        creator = db.query(User).filter(User.id == creator_id, User.deleted == False).first()
        if not creator:
            await _send_json(websocket, {"type": "error", "message": "Creator not found"})
            await websocket.close(code=1008)
            return
    except Exception as exc:
        logger.error("DB error validating creator %s: %s", creator_id, exc)
        await websocket.close(code=1011)
        db.close()
        return

    gemini_url = f"{_GEMINI_WS_BASE}?key={settings.GEMINI_API_KEY}"

    try:
        async with websockets.connect(
            gemini_url,
            ping_interval=20,
            ping_timeout=20,
        ) as gemini_ws:

            # First message: session setup
            await gemini_ws.send(json.dumps(build_setup_message()))

            # Wait for setupComplete before telling the client we're ready
            setup_ok = await _wait_for_setup(gemini_ws, websocket)
            if not setup_ok:
                return

            await _send_json(websocket, {
                "type": "session_ready",
                "input_sample_rate": 16000,
                "output_sample_rate": 24000,
            })

            client_task = asyncio.create_task(
                _client_to_gemini(websocket, gemini_ws)
            )
            gemini_task = asyncio.create_task(
                _gemini_to_client(websocket, gemini_ws, db, creator_id)
            )

            done, pending = await asyncio.wait(
                [client_task, gemini_task],
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
        detail = f"Gemini rejected connection: HTTP {exc.status_code}"
        logger.error("Gemini handshake failed (creator=%s): %s", creator_id, exc)
        await _send_json(websocket, {"type": "error", "message": detail})
    except websockets.exceptions.ConnectionClosedError as exc:
        logger.warning("Gemini Live WS closed (creator=%s): code=%s reason=%s", creator_id, exc.code, exc.reason)
        await _send_json(websocket, {"type": "error", "message": f"Gemini closed: code={exc.code} reason={exc.reason}"})
    except Exception as exc:
        logger.exception("Gemini voice session error (creator=%s): %s", creator_id, exc)
        await _send_json(websocket, {"type": "error", "message": str(exc)})
    finally:
        db.close()
        try:
            await websocket.close()
        except Exception:
            pass


# ── Setup handshake ───────────────────────────────────────────────────────────

async def _wait_for_setup(gemini_ws, client_ws: WebSocket, timeout: float = 10.0) -> bool:
    """Wait for Gemini's setupComplete acknowledgement."""
    try:
        async with asyncio.timeout(timeout):
            async for raw in gemini_ws:
                logger.info("Gemini setup msg: %s", raw[:500])
                event = json.loads(raw)
                if "setupComplete" in event:
                    return True
                if "error" in event:
                    msg = event["error"].get("message", "Setup failed")
                    logger.error("Gemini setup error: %s", event["error"])
                    await _send_json(client_ws, {"type": "error", "message": f"Gemini setup error: {msg}"})
                    return False
            # for-loop ended — Gemini closed the connection without setupComplete
            logger.error("Gemini closed connection before setupComplete")
            await _send_json(client_ws, {"type": "error", "message": "Gemini closed connection during setup"})
    except TimeoutError:
        logger.error("Gemini setup timed out after %ss", timeout)
        await _send_json(client_ws, {"type": "error", "message": "Gemini setup timed out"})
    except Exception as exc:
        logger.exception("Gemini setup exception: %s", exc)
        await _send_json(client_ws, {"type": "error", "message": str(exc)})
    return False


# ── Client → Gemini ───────────────────────────────────────────────────────────

async def _client_to_gemini(client_ws: WebSocket, gemini_ws) -> None:
    """Forward audio and control messages from the browser to Gemini."""
    try:
        while True:
            msg = await client_ws.receive()

            if "bytes" in msg and msg["bytes"]:
                # Raw PCM-16 audio at 16kHz
                audio_b64 = base64.b64encode(msg["bytes"]).decode()
                await gemini_ws.send(json.dumps({
                    "realtimeInput": {
                        "mediaChunks": [
                            {
                                "mimeType": "audio/pcm;rate=16000",
                                "data": audio_b64,
                            }
                        ]
                    }
                }))

            elif "text" in msg and msg["text"]:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "interrupt":
                    # Ask Gemini to stop the current response
                    # Gemini handles interruption automatically via VAD,
                    # but we can signal it by ending the client turn
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("client_to_gemini stopped: %s", exc)


# ── Gemini → Client ───────────────────────────────────────────────────────────

async def _gemini_to_client(client_ws: WebSocket, gemini_ws, db, creator_id: int) -> None:
    """Forward Gemini events to the browser; handle function calls server-side."""
    try:
        async for raw in gemini_ws:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # ── AI audio output ───────────────────────────────────────────────
            server_content = event.get("serverContent", {})
            if server_content:
                model_turn = server_content.get("modelTurn", {})
                parts = model_turn.get("parts", [])

                for part in parts:
                    inline = part.get("inlineData", {})
                    mime = inline.get("mimeType", "")
                    data_b64 = inline.get("data", "")

                    if "audio" in mime and data_b64:
                        try:
                            audio_bytes = base64.b64decode(data_b64)
                            await client_ws.send_bytes(audio_bytes)
                        except Exception:
                            pass

                    # AI text transcription (when response_modalities includes TEXT)
                    text = part.get("text", "")
                    if text:
                        await _send_json(client_ws, {
                            "type": "ai_transcript",
                            "text": text,
                        })

                # Input transcription (user speech → text)
                input_trans = server_content.get("inputTranscription", {})
                if input_trans.get("text"):
                    await _send_json(client_ws, {
                        "type": "user_transcript",
                        "text": input_trans["text"],
                    })

                # Output transcription (alternative field for AI text)
                output_trans = server_content.get("outputTranscription", {})
                if output_trans.get("text"):
                    await _send_json(client_ws, {
                        "type": "ai_transcript",
                        "text": output_trans["text"],
                    })

                # VAD signals
                if server_content.get("inputAudioBufferEmpty") is False:
                    await _send_json(client_ws, {"type": "user_speech_started"})
                if server_content.get("interrupted"):
                    await _send_json(client_ws, {"type": "user_speech_started"})

            # ── Function calls ────────────────────────────────────────────────
            tool_call = event.get("toolCall", {})
            fn_calls = tool_call.get("functionCalls", [])
            if fn_calls:
                responses = []
                for fc in fn_calls:
                    call_id = fc.get("id", "")
                    fn_name = fc.get("name", "")
                    args = fc.get("args", {})
                    args_str = json.dumps(args) if isinstance(args, dict) else str(args)

                    result_str = dispatch_function_call(fn_name, args_str, db, creator_id)

                    # Notify client if a mission was created
                    if fn_name == "create_mission":
                        try:
                            r = json.loads(result_str)
                            if r.get("success"):
                                await _send_json(client_ws, {
                                    "type": "mission_created",
                                    "mission_id": r.get("mission_id"),
                                    "title": r.get("title"),
                                    "executor": r.get("executor"),
                                    "deadline": r.get("deadline"),
                                })
                        except Exception:
                            pass

                    try:
                        result_obj = json.loads(result_str)
                    except Exception:
                        result_obj = {"output": result_str}

                    responses.append({
                        "id": call_id,
                        "name": fn_name,
                        "response": result_obj,
                    })

                # Send all responses back to Gemini in one message
                await gemini_ws.send(json.dumps({
                    "toolResponse": {
                        "functionResponses": responses
                    }
                }))

            # ── Errors ────────────────────────────────────────────────────────
            error = event.get("error", {})
            if error:
                msg = error.get("message", "Unknown Gemini error")
                logger.warning("Gemini Live error: %s", msg)
                await _send_json(client_ws, {"type": "error", "message": msg})

    except websockets.exceptions.ConnectionClosed:
        pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("gemini_to_client stopped: %s", exc)


# ── Helper ────────────────────────────────────────────────────────────────────

async def _send_json(ws: WebSocket, data: dict) -> None:
    try:
        await ws.send_text(json.dumps(data))
    except Exception:
        pass
