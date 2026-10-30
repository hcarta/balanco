"""Vereditos de checagem a partir do título."""
import pytest

from factcheck import verdict_from_title


@pytest.mark.parametrize("title,expected", [
    ("É #FAKE que governo federal recuou sobre fim da escala 6x1", "falso"),
    ("É falso que Bolsonaro foi enviado de volta à Papuda", "falso"),
    ("Documento falso distorce dados do TSE", "falso"),
    ("É #FATO que vacina reduz internações, apontam estudos", "verdadeiro"),
    ("Veja o que é #FATO ou #FAKE no debate da Globo", "checagem"),
    ("Número de eleitores maior que o de habitantes não indica fraude", "enganoso"),
    ("Reportagem que mostra cortes não é atual; vídeo é de 2024", "enganoso"),
    ("Vídeo de professores em greve é de paralisação e não tem relação com corte", "enganoso"),
    ("Prefeitura anuncia novo parque na zona sul", "checagem"),
])
def test_verdict_from_title(title, expected):
    assert verdict_from_title(title) == expected
