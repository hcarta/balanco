"""Integridade de sources.yaml + governança (Fase 5).

Garante que nenhuma fonte entra quebrada (sem rss, viés fora da escala,
fetcher inválido, id duplicado) e que toda fonte está na tabela de curadoria.
"""
import os

import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_sources():
    with open(os.path.join(BASE, "sources.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def load_curation_ids():
    import re
    txt = open(os.path.join(BASE, "CURADORIA_VIES.md"), encoding="utf-8").read()
    # nomes na tabela de curadoria: linhas "| Nome | viés |"
    return set(re.findall(r"^\| ([^|]+) \| [+-]?\d", txt, re.M))


def load_curation_factuality():
    import re
    txt = open(os.path.join(BASE, "CURADORIA_VIES.md"), encoding="utf-8").read()
    m = re.search(r"## 5\. Factualidade.*?(?=\n## |\Z)", txt, re.S)
    section = m.group(0) if m else ""
    return set(re.findall(r"^\| ([^|]+) \| (?:very_high|high|mixed|low|very_low) \|", section, re.M))


def test_sources_valid():
    srcs = load_sources()
    assert len(srcs) >= 20, "esperava ao menos 20 fontes"
    ids = [s["id"] for s in srcs]
    assert len(ids) == len(set(ids)), "ids duplicados"
    for s in srcs:
        assert s.get("name"), f"{s.get('id')}: sem nome"
        assert s.get("rss", "").startswith("http"), f"{s['id']}: rss inválido"
        assert s.get("fetcher", "rss") in ("rss", "sitemap"), f"{s['id']}: fetcher inválido"
        assert s.get("kind", "br") in ("br", "intl"), f"{s['id']}: kind inválido"
        assert isinstance(s.get("longform", False), bool), f"{s['id']}: longform inválido"
        assert -2.0 <= float(s.get("bias", 0)) <= 2.0, f"{s['id']}: viés fora da escala"
        assert s.get("factuality") in ("very_high", "high", "mixed", "low", "very_low"), \
            f"{s['id']}: factualidade inválida"
        assert s.get("ownership"), f"{s['id']}: sem ownership"


def test_all_sources_in_curation():
    srcs = load_sources()
    names = load_curation_ids()
    missing = [s["name"] for s in srcs if s["name"] not in names]
    assert not missing, f"fontes sem justificativa na curadoria: {missing}"


def test_all_sources_have_factuality_rationale():
    srcs = load_sources()
    names = load_curation_factuality()
    missing = [s["name"] for s in srcs if s["name"] not in names]
    assert not missing, f"fontes sem justificativa de factualidade na curadoria: {missing}"
    from collections import Counter
    got = Counter(s["factuality"] for s in srcs)
    assert set(got) <= {"very_high", "high", "mixed", "low", "very_low"}
    assert "very_low" not in got, "very_low exigiria evidência de desinformação sistemática"


def test_validate_sources_catches_missing_and_bad_values():
    import app
    ok = [{"id": "a", "name": "A", "rss": "https://a/rss", "bias": 0.5,
           "factuality": "high"}]
    assert app.validate_sources(ok) == []
    bad = [
        {"id": "a", "name": "A", "rss": "https://a", "bias": 5,
         "factuality": "alta"},
        {"id": "a", "name": "", "bias": 0.0, "factuality": "high"},
        {"id": "b", "name": "B", "rss": "https://b", "bias": 0,
         "factuality": "high", "fetcher": "ftp"},
    ]
    errs = app.validate_sources(bad)
    joined = " | ".join(errs)
    assert "bias 5.0 fora" in joined
    assert "factuality inválida" in joined
    assert "id duplicado" in joined
    assert "nome ausente" in joined
    assert "fetcher inválido" in joined
