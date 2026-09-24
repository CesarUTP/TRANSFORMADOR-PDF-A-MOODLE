"""
list_models.py — Lista los modelos de Gemini disponibles para la API key
configurada (la guardada en la app, o GEMINI_API_KEY en el entorno/.env) que admiten
generateContent.

    backend/venv/bin/python dev/list_models.py
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from credenciales import get_api_key  # noqa: E402

resp = requests.get(
    "https://generativelanguage.googleapis.com/v1beta/models",
    headers={"x-goog-api-key": get_api_key()},
    params={"pageSize": 1000},
    timeout=30,
)
resp.raise_for_status()
for m in resp.json().get("models", []):
    if "generateContent" in m.get("supportedGenerationMethods", []):
        print(m["name"])
