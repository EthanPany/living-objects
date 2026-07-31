"""Catalog of the 30 Gemini prebuilt voices.

Pure data module: no third-party imports, no side effects. Safe to import from
the FastAPI server (to serve GET /voices) and from preview_voices.py.
"""

VOICES = [
    {"name": "Zephyr", "character": "Bright"},
    {"name": "Puck", "character": "Upbeat"},
    {"name": "Charon", "character": "Informative"},
    {"name": "Kore", "character": "Firm"},
    {"name": "Fenrir", "character": "Excitable"},
    {"name": "Leda", "character": "Youthful"},
    {"name": "Orus", "character": "Firm"},
    {"name": "Aoede", "character": "Breezy"},
    {"name": "Callirrhoe", "character": "Easy-going"},
    {"name": "Autonoe", "character": "Bright"},
    {"name": "Enceladus", "character": "Breathy"},
    {"name": "Iapetus", "character": "Clear"},
    {"name": "Umbriel", "character": "Easy-going"},
    {"name": "Algieba", "character": "Smooth"},
    {"name": "Despina", "character": "Smooth"},
    {"name": "Erinome", "character": "Clear"},
    {"name": "Algenib", "character": "Gravelly"},
    {"name": "Rasalgethi", "character": "Informative"},
    {"name": "Laomedeia", "character": "Upbeat"},
    {"name": "Achernar", "character": "Soft"},
    {"name": "Alnilam", "character": "Firm"},
    {"name": "Schedar", "character": "Even"},
    {"name": "Gacrux", "character": "Mature"},
    {"name": "Pulcherrima", "character": "Forward"},
    {"name": "Achird", "character": "Friendly"},
    {"name": "Zubenelgenubi", "character": "Casual"},
    {"name": "Vindemiatrix", "character": "Gentle"},
    {"name": "Sadachbia", "character": "Lively"},
    {"name": "Sadaltager", "character": "Knowledgeable"},
    {"name": "Sulafat", "character": "Warm"},
]

# Convenience lookups (still zero side effects worth worrying about).
VOICE_NAMES = [v["name"] for v in VOICES]
VOICE_BY_NAME = {v["name"]: v for v in VOICES}

DEFAULT_VOICE = "Kore"


def is_valid_voice(name: str) -> bool:
    """True if `name` is one of the 30 prebuilt voice names (case-sensitive)."""
    return name in VOICE_BY_NAME


def resolve_voice(name: str | None) -> str:
    """Return a usable voice name, falling back to DEFAULT_VOICE."""
    if name and name in VOICE_BY_NAME:
        return name
    return DEFAULT_VOICE


if __name__ == "__main__":
    for v in VOICES:
        print(f"{v['name']:<16} {v['character']}")
    print(f"\n{len(VOICES)} voices")
