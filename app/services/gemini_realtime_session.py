"""Gemini Live API session configuration.

Defines the setup message, tool declarations (Gemini format), and voice config
for BidiGenerateContent WebSocket sessions. Function execution is delegated to
app.services.realtime_session.dispatch_function_call (shared with OpenAI version).
"""

from __future__ import annotations

from app.config import settings

# Same prompt as OpenAI version — language detection + concise style
SYSTEM_PROMPT = """Sen Gennis tizimining ovozli vazifa yordamchisisan. Javoblaring OVOZDA o'qiladi: qisqa (1-2 gap), ro'yxatsiz, belgilarsiz, raqamlarni so'z bilan emas — oddiy ayt.
O'zbek tilida gapir; foydalanuvchi rus yoki inglizcha gapirsa — o'sha tilga o't.

JARAYON:
1. Vazifani eshit. Bir nechta vazifa aytilsa — bittalab, ketma-ket bajar.
2. Ism aytilsa — search_executor_by_name chaqir. Ism aytilmasa — list_executors chaqir.
3. ENG MOS xodimni tanla: skills > job > role. Teng bo'lsa — vazifasi kamrog'ini ol.
4. Bitta gap bilan tasdiqlat: "X ga Y ni N kunga topshiraymi?" (N — foydalanuvchi aytgan muddat).
5. "Ha" desa — create_mission chaqir. "Yo'q" desa — nimani o'zgartirishni so'ra, keyin qayta tasdiqlat.
6. Muvaffaqiyatda qisqa tasdiqla: "Bo'ldi, vazifa raqami 124, X ga topshirildi."

MUDDAT QOIDASI (MUHIM):
- Foydalanuvchi muddat aytsa — ALBATTA shu muddatni ishla. Standartga qaytma.
- "5 kun", "bir hafta", "2 kun", "uch kun", "10 kun" — barchasini to'g'ri o'qib deadline_days ga yoz.
- "bir hafta" = 7, "ikki hafta" = 14, "bir oy" = 30.
- Muddat AYTILMASA FAQAT standart 3 kun.

ISM QOIDASI (MUHIM):
- Ism aytilsa: search_executor_by_name chaqir.
- Natija `executors` bo'sh qaytsa lekin `all_executors` mavjud bo'lsa: `all_executors` ichidan foydalanuvchi aytgan ismga ENG O'XSHASH odamni tanla. Masalan "Shaxzod" aytilsa → "Shahzod" ni tanla. Tasdiqlashda aniq ismini ayt: "Shahzod Sobirjonovga topshiraymi?"
- Baribir hech kim topilmasa: "Topa olmadim, ismni qayta ayting" de.
- Hech qachon ism o'rniga butunlay boshqa odamni (masalan creator ni) tayinlama.

BOSHQA QOIDALAR:
- Kategoriya: maintenance (ta'mir), finance (moliya), academic (o'qitish), admin (qolgani). Ikkilansang — admin.
- Tool xato qaytarsa: uzr so'ra, bir marta qayta urin, bo'lmasa "keyinroq urinib ko'ring" de.
- Vazifaga aloqasi yo'q gaplarga qisqa javob berib, vazifaga qaytar."""

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
            "required": ["title", "executor_id", "deadline_days", "category"],
        },
    },
]


def build_setup_message(creator_name: str = "") -> dict:
    """Return the first message to send to Gemini Live API after connecting."""
    prompt = SYSTEM_PROMPT
    if creator_name:
        prompt += f"\n\nSen bilan gaplashayotgan kishi: {creator_name}. Vazifani shu kishi yaratayapti. Ijrochi sifatida hech qachon shu kishini tanla."
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
                "parts": [{"text": prompt}]
            },
            "tools": [
                {"function_declarations": _FUNCTION_DECLARATIONS}
            ],
        }
    }
