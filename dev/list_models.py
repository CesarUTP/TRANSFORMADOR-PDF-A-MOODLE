"""
list_models.py — Lista los modelos de Gemini disponibles para la API key
configurada (GEMINI_API_KEY en el entorno o en .env) que admiten
generateContent.

    backend/venv/bin/python dev/list_models.py
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from config import GEMINI_API_KEY  # noqa: E402

resp = requests.get(
    "https://generativelanguage.googleapis.com/v1beta/models",
    headers={"x-goog-api-key": GEMINI_API_KEY},
    params={"pageSize": 1000},
    timeout=30,
)
resp.raise_for_status()
for m in resp.json().get("models", []):
    if "generateContent" in m.get("supportedGenerationMethods", []):
        print(m["name"])
