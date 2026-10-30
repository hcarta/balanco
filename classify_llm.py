"""Classificação de viés por LLM (OpenAI-compatível). Opcional — sem chave usa heurística."""
import json
import os
import urllib.request

PROMPT = """Você é um analista de mídia brasileiro imparcial.
Classifique o VIÉS POLÍTICO do artigo abaixo no contexto brasileiro atual.

Escala:
-2 = extrema-esquerda (linguagem militante pró-governo Lula/esquerda, demoniza direita)
-1 = esquerda (enquadramento favorável à esquerda/progressismo)
0 = centro (factual, múltiplos lados, sem loaded words)
+1 = direita (enquadramento favorável à direita/conservadorismo, pró-Bolsonaro/mercado)
+2 = extrema-direita (linguagem militante pró-Bolsonaro/direita, demoniza esquerda)

Considere: escolha de palavras, enquadramento, omissão aparente, fonte citada.
Responda SOMENTE JSON: {"score": <int -2..2>, "confianca": <0..1>, "motivo": "<curto>"}"""

def _call_chat(title: str, summary: str, source: str) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": f"FONTE: {source}\nTÍTULO: {title}\nRESUMO: {summary[:1200]}"},
        ],
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read().decode())
        txt = out["choices"][0]["message"]["content"].strip()
        # extrai JSON mesmo com cercas ```json
        if "```" in txt:
            txt = txt.split("```")[-2] if txt.count("```") >= 2 else txt.replace("```", "")
            txt = txt.replace("json", "", 1).strip()
        s, e = txt.find("{"), txt.rfind("}") + 1
        data = json.loads(txt[s:e])
        score = max(-2, min(2, int(data.get("score", 0))))
        return {"score": score, "confianca": float(data.get("confianca", 0.5)), "motivo": str(data.get("motivo", ""))[:200]}
    except Exception as ex:
        print(f"  [llm] falha em '{title[:50]}': {ex}")
        return None


def classify_batch(articles: list[dict]) -> dict[str, dict]:
    """Retorna {article_key: {score, confianca, motivo, via}}. Só chama API se houver chave."""
    if not os.getenv("OPENAI_API_KEY"):
        return {}
    out: dict[str, dict] = {}
    print(f"[llm] classificando {len(articles)} artigos via {os.getenv('LLM_MODEL', 'gpt-4o-mini')}...")
    for i, a in enumerate(articles):
        key = a["link"]
        r = _call_chat(a.get("title", ""), a.get("summary", ""), a.get("source_name", ""))
        if r:
            r["via"] = "llm"
            out[key] = r
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(articles)}")
    return out
