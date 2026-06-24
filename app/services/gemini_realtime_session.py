"""Gemini Live API session configuration.

Defines the setup message, tool declarations (Gemini format), and voice config
for BidiGenerateContent WebSocket sessions. Function execution is delegated to
app.services.realtime_session.dispatch_function_call (shared with OpenAI version).
"""

from __future__ import annotations

from app.config import settings

# Same prompt as OpenAI version — language detection + concise style
SYSTEM_PROMPT = """You are a voice mission assistant for the Gennis management system.
You help managers, directors, and team leaders create work missions through natural conversation.

LANGUAGE RULE: The user may speak in Uzbek, Russian, or English. You MUST detect and respond in the exact same language they use. Do NOT switch languages.

YOUR WORKFLOW:
1. Listen to what work the manager describes.
2. If an executor is mentioned by name, call search_executor_by_name to find them.
3. If no executor is mentioned, call list_executors and suggest the most relevant person.
4. Confirm the details (who, what, deadline) in one short sentence before creating.
5. Call create_mission to create it.
6. Confirm success with the mission ID.

RULES:
- Be concise. No long explanations.
- Ask only ONE clarifying question at a time.
- Default deadline: 3 days from today, unless specified otherwise.
- Default category: "admin", unless the task clearly belongs to another.
- If the manager mentions multiple tasks, handle them one at a time.
- Never invent executor names — always look them up first.

Examples of how you speak:
- Uzbek: "Topshiriq yaratildi: Ali Karimovga 3 kunlik ta'mirlash vazifasi (ID: 42)."
- Russian: "Задание создано: Алишер — ремонт офиса, срок 3 дня (ID: 42)."
- English: "Mission created: Ali — office repair, due in 3 days (ID: 42)."
"""

# Gemini function declarations (OpenAPI-style JSON Schema)
_FUNCTION_DECLARATIONS = [
    {
        "name": "list_executors",
        "description": (
            "List all active users available as mission executors. "
            "Returns their id, full name, role, and job title."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "search_executor_by_name",
        "description": (
            "Search for an active user by name (case-insensitive, partial match). "
            "Use this when the manager mentions someone by name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "First or last name (or partial) to search for.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_mission",
        "description": "Create a new work mission and assign it to an executor.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short, action-oriented mission title.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description. Optional.",
                },
                "executor_id": {
                    "type": "integer",
                    "description": "User ID of the person who will execute this mission.",
                },
                "creator_id": {
                    "type": "integer",
                    "description": "User ID of the manager creating this mission.",
                },
                "deadline_days": {
                    "type": "integer",
                    "description": "Days from today for the deadline. Default 3.",
                },
                "category": {
                    "type": "string",
                    "description": "Mission category.",
                    "enum": [
                        "academic", "admin", "student", "report",
                        "meeting", "marketing", "maintenance", "finance",
                    ],
                },
            },
            "required": ["title", "executor_id", "creator_id", "deadline_days", "category"],
        },
    },
]


def build_setup_message() -> dict:
    """Return the first message to send to Gemini Live API after connecting."""
    return {
        "setup": {
            "model": settings.GEMINI_REALTIME_MODEL,
            "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": settings.GEMINI_VOICE,
                        }
                    }
                },
            },
            "system_instruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "tools": [
                {"function_declarations": _FUNCTION_DECLARATIONS}
            ],
        }
    }
