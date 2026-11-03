"""Matriz de variantes dos conceitos de capa (P1/P4): plural e paráfrase.

Cada pauta tem exemplos que DEVEM casar e exemplos que NÃO podem ser
atribuídos a ela. É o equivalente, para o lexicon, dos pares rotulados do
viés: qualquer mudança futura que quebre uma variante falha aqui.
"""
import app


POSITIVOS = {
    "Eleição EUA / Trump": [
        "Eleições nos Estados Unidos definem o Senado",
        "Eleições de meio de mandato mobilizam democratas",
        "Midterms decidem a força de Trump",
        "Voto antecipado bate recorde",
        "Casa Branca prepara plano pós-eleição",
        "Presidente dos EUA pode perder o Senado? Veja projeções",
    ],
    "Lula / juros e economia": [
        "Taxa de juros deve ficar em dois dígitos",
        "Copom eleva a Selic",
        "Ajuste fiscal divide o governo",
        "Durigan defende a política monetária",
    ],
    "Flávio Bolsonaro": [
        "Fuga de Flávio Bolsonaro aos EUA leva militares a Tarcísio",
        "Flávio Bolsonaro recorre de apreensão de passaportes",
        "Senador derrotado deixa o Congresso",
    ],
    "Reforma eleitoral": [
        "Reforma eleitoral avança na Câmara",
        "Puxadores de voto entram na mira",
        "Distritão volta à discussão",
    ],
    "Tarcísio / Linha 6": [
        "Tarcísio adia entrega da Linha 6",
        "Governo Tarcísio promete a Linha Laranja",
    ],
    "Binance": [
        "Binance suspende saques após ataque",
    ],
    "Ataque hacker / freezers": [
        "Freezers de supermercados são alvo de hackers",
    ],
    "Queda de avião": [
        "Avião cai na Flórida",
        "Aviões caem na Flórida",
        "Copilota era brasileira",
        "Acidente aéreo deixa nove mortos",
    ],
    "Inadimplência": [
        "Inadimplência bate recorde",
        "Serasa aponta 84 milhões de negativados",
    ],
    "Obesidade / SUS": [
        "Obesidade cresce no SUS",
        "Cirurgia bariátrica pelo SUS",
    ],
    "Vale-refeição": [
        "Vale-refeição tem novo limite",
        "Vale-alimentação muda regra",
    ],
    "Argentina / Milei": [
        "Milei enfrenta protestos",
        "Casa Rosada nega ajuda",
    ],
    "Irã / Hormuz": [
        "Irã propõe reabrir Hormuz",
        "Khamenei adverte os Estados Unidos",
    ],
}

NEGATIVOS = {
    "Eleição EUA / Trump": [
        "Bebê morre após ser atingido por abacate na Argentina",
        "Copom eleva a Selic",
    ],
    "Lula / juros e economia": [
        "Binance suspende saques",
        "Freezers de supermercados são alvo de hackers",
    ],
    "Flávio Bolsonaro": [
        "Milei enfrenta protestos",
        "Tarcísio adia entrega da Linha 6",
    ],
    "Reforma eleitoral": ["Copom eleva a Selic"],
    "Tarcísio / Linha 6": ["Flávio Bolsonaro recorre de apreensão"],
    "Binance": ["Freezers de supermercados são alvo de hackers"],
    "Ataque hacker / freezers": ["Binance suspende saques"],
    "Queda de avião": ["Irã propõe reabrir Hormuz"],
    "Inadimplência": ["Copom eleva a Selic"],
    "Obesidade / SUS": ["Vale-refeição tem novo limite"],
    "Vale-refeição": ["Obesidade cresce no SUS"],
    "Argentina / Milei": ["Flávio Bolsonaro recorre de apreensão"],
    "Irã / Hormuz": ["Milei enfrenta protestos"],
}


def test_normalizacao_singulariza_e_preserva_nomes():
    assert app.sing_pt("Eleições") == "eleição"
    assert app.sing_pt("Aviões") == "avião"
    assert app.sing_pt("Militares") == "militar"
    assert app.sing_pt("Juros") == "juro"
    assert app.sing_pt("Estados Unidos") == "estados unidos"
    assert app.norm_tokens("Juros altos") == ("juro", "alto")


def test_plural_nao_depende_do_regex_original():
    """A sombra singularizada resolve o plural, não o regex ad-hoc."""
    rx = dict(app.FRONT_CONCEPTS)["Eleição EUA / Trump"]
    titulo = "Eleições nos Estados Unidos definem o Senado"
    assert not rx.search(titulo)          # o regex sozinho não casaria
    assert app.concept_of(titulo) == "Eleição EUA / Trump"


def test_variantes_positivas_por_conceito():
    for label, titulos in POSITIVOS.items():
        for titulo in titulos:
            assert app.concept_of(titulo) == label, titulo


def test_variantes_negativas_por_conceito():
    for label, titulos in NEGATIVOS.items():
        for titulo in titulos:
            assert app.concept_of(titulo) != label, (label, titulo)
