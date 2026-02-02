from __future__ import annotations
from pathlib import Path
import json
from typing import Dict, List

LOCALE_DIR = Path(__file__).resolve().parent / "i18n"


def available_languages() -> List[str]:
    if not LOCALE_DIR.exists():
        return []
    return sorted(p.stem for p in LOCALE_DIR.glob("*.json"))


def load_translations(lang: str) -> Dict[str, str]:
    path = LOCALE_DIR / f"{lang}.json"
    if not path.exists():
        # fallback to 'de' then 'en'
        path = LOCALE_DIR / "de.json"
        if not path.exists():
            return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def language_label(lang: str) -> str:
    # Use translation file's own labels if present
    tr = load_translations(lang)
    return tr.get(lang, lang)
