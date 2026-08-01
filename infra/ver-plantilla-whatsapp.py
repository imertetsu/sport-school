import re
import httpx
from app.core.config import settings

V, WABA, TOK = settings.whatsapp_graph_version, settings.whatsapp_waba_id, settings.whatsapp_access_token
r = httpx.get(
    f"https://graph.facebook.com/{V}/{WABA}/message_templates",
    params={"limit": 50, "fields": "name,status,language,components"},
    headers={"Authorization": f"Bearer {TOK}"}, timeout=20,
)
for t in r.json().get("data", []):
    if t.get("name") != "recordatorio_mora":
        continue
    print("plantilla:", t["name"], "|", t["language"], "|", t["status"])
    for c in t.get("components", []):
        if c.get("type") == "HEADER":
            print("  HEADER formato =", c.get("format"))
        elif c.get("type") == "BODY":
            txt = c.get("text", "")
            variables = sorted(set(re.findall(r"\{\{(\d+)\}\}", txt)), key=int)
            print("  BODY variables =", variables)
            print("  ---- texto aprobado en Meta ----")
            for linea in txt.split("\n"):
                print("   ", linea)
