import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.templates import SEGMENTOS, get_template, list_templates, validate_respostas

TIPOS = {"currency", "percent", "number", "integer", "select", "multiselect", "boolean", "text"}
COMUNS = {
    "faturamento_mensal", "margem_bruta_pct", "prazo_medio_recebimento_dias",
    "prazo_medio_pagamento_dias", "folha_mensal", "dividas_total", "parcela_dividas_mensal",
    "possui_estoque", "valor_estoque", "sazonalidade",
}
VALORES = {"currency": 15000.5, "percent": 35, "number": 3, "integer": 6, "boolean": False, "text": "Loja"}


def campos(template):
    return [campo for secao in template["secoes"] for campo in secao["campos"]]


def respostas_validas(segmento):
    respostas = {}
    for campo in campos(get_template(segmento)):
        if campo["tipo"] == "select":
            respostas[campo["id"]] = campo["opcoes"][0]
        elif campo["tipo"] == "multiselect":
            respostas[campo["id"]] = campo["opcoes"][:2]
        else:
            respostas[campo["id"]] = VALORES[campo["tipo"]]
    return respostas


def erro(segmento, **changes):
    respostas = respostas_validas(segmento) | changes
    return {e["campo"]: e["erro"] for e in validate_respostas(segmento, respostas)}


# --- estrutura dos templates ----------------------------------------------------------------------

def test_segmentos_na_ordem_do_contrato():
    assert SEGMENTOS == (
        "varejo", "alimentacao", "servicos", "saude", "tecnologia", "industria", "agro", "construcao", "outro",
    )
    assert [t["segmento"] for t in list_templates()] == list(SEGMENTOS)


@pytest.mark.parametrize("segmento", SEGMENTOS)
def test_estrutura_do_template(segmento):
    template = get_template(segmento)
    assert {"segmento", "versao", "nome", "descricao", "icone", "secoes"} <= template.keys()
    todos = campos(template)
    ids = [c["id"] for c in todos]
    assert 8 <= len(todos) <= 14
    assert len(ids) == len(set(ids))
    assert len({s["id"] for s in template["secoes"]}) == len(template["secoes"])
    for campo in todos:
        assert campo["tipo"] in TIPOS
        assert campo["label"]
        if campo["tipo"] in ("select", "multiselect"):
            assert campo["opcoes"] and len(campo["opcoes"]) == len(set(campo["opcoes"]))
    assert COMUNS <= set(ids)


def test_ids_compartilhados_tem_o_mesmo_tipo_em_todos_os_segmentos():
    tipos = {}
    for template in list_templates():
        for campo in campos(template):
            if campo["id"] != "tipo_estabelecimento":  # select com opções diferentes por segmento
                assert tipos.setdefault(campo["id"], campo) == campo
    assert tipos["pct_cartao_credito"]["tipo"] == "percent"
    assert tipos["ticket_medio"]["tipo"] == "currency"


def test_templates_retornados_sao_copias():
    get_template("varejo")["secoes"].clear()
    list_templates()[0]["nome"] = "x"
    assert get_template("varejo")["secoes"] and list_templates()[0]["nome"] == "Varejo e e-commerce"
    assert get_template("inexistente") is None


# --- validação ------------------------------------------------------------------------------------

@pytest.mark.parametrize("segmento", SEGMENTOS)
def test_respostas_validas(segmento):
    assert validate_respostas(segmento, respostas_validas(segmento)) == []


def test_segmento_desconhecido():
    assert validate_respostas("cassino", {}) == [{"campo": "segmento", "erro": "Segmento desconhecido: 'cassino'."}]


def test_respostas_que_nao_sao_objeto():
    assert validate_respostas("varejo", [])[0]["campo"] == "respostas"


def test_obrigatorios_ausentes_ou_vazios():
    respostas = respostas_validas("varejo")
    del respostas["faturamento_mensal"]
    respostas |= {"sazonalidade": "  ", "folha_mensal": None, "canais": [], "ticket_medio": None}
    erros = {e["campo"]: e["erro"] for e in validate_respostas("varejo", respostas)}
    assert erros == {c: "Campo obrigatório." for c in ("faturamento_mensal", "sazonalidade", "folha_mensal")}


def test_campos_extras_sao_ignorados():
    assert validate_respostas("varejo", respostas_validas("varejo") | {"campo_novo": "x"}) == []


def test_valor_estoque_obrigatorio_quando_possui_estoque():
    assert erro("varejo", possui_estoque=True, valor_estoque=None) == {"valor_estoque": "Campo obrigatório."}
    assert erro("varejo", possui_estoque=True, valor_estoque=50000) == {}
    assert erro("varejo", possui_estoque=False, valor_estoque=None) == {}


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("faturamento_mensal", "muito", "Informe um número."),
        ("faturamento_mensal", True, "Informe um número."),
        ("faturamento_mensal", float("nan"), "Informe um número."),
        ("folha_mensal", -1, "O valor não pode ser negativo."),
        ("margem_bruta_pct", 120, "Informe um percentual entre 0 e 100."),
        ("margem_bruta_pct", -5, "O valor não pode ser negativo."),
        ("prazo_medio_recebimento_dias", 30.5, "Informe um número inteiro."),
        ("prazo_medio_recebimento_dias", True, "Informe um número inteiro."),
        ("prazo_medio_recebimento_dias", 400, "O valor máximo é 365."),
        ("parcelamento_medio", 0.5, "O valor mínimo é 1."),
        ("possui_estoque", "sim", "Informe sim ou não."),
        ("sazonalidade", "Altíssima", "Escolha uma das opções: Baixa, Média, Alta."),
        ("sazonalidade", ["Alta"], "Escolha uma das opções: Baixa, Média, Alta."),
        ("canais", "Marketplace", "Envie uma lista de opções."),
        ("canais", ["Marketplace", "Telefone"], "Opções inválidas: Telefone."),
    ],
)
def test_erros_de_tipo_e_limite(campo, valor, mensagem):
    assert erro("varejo", **{campo: valor}) == {campo: mensagem}


def test_texto():
    assert erro("outro", descricao_atividade=42) == {"descricao_atividade": "Informe um texto."}
    assert erro("outro", descricao_atividade="x" * 501) == {
        "descricao_atividade": "Use no máximo 500 caracteres."
    }


def test_limite_padrao_de_texto(monkeypatch):
    from app.templates import validation

    campo = {"id": "obs", "label": "Obs", "tipo": "text"}
    template = {"secoes": [{"id": "s", "titulo": "S", "campos": [campo]}]}
    monkeypatch.setattr(validation, "TEXT_MAX_LENGTH", 3)
    assert validation.validate_template_respostas(template, {"obs": "abcd"}) == [
        {"campo": "obs", "erro": "Use no máximo 3 caracteres."}
    ]
    assert validation._fmt(2.5) == "2,5"


def test_limites_de_mes_e_area_no_agro():
    assert erro("agro", mes_colheita=13) == {"mes_colheita": "O valor máximo é 12."}
    assert erro("agro", mes_colheita=0) == {"mes_colheita": "O valor mínimo é 1."}
    assert erro("agro", area_hectares=None) == {"area_hectares": "Campo obrigatório."}


# --- rotas ----------------------------------------------------------------------------------------

def test_lista_templates_autenticado(client):
    response = client.get("/onboarding/templates")
    assert response.status_code == 200
    assert response.json() == list_templates()


def test_template_por_segmento(client):
    assert client.get("/onboarding/templates/agro").json()["icone"] == "wheat"
    assert client.get("/onboarding/templates/cassino").status_code == 404


@pytest.mark.parametrize("path", ["/onboarding/templates", "/onboarding/templates/varejo"])
def test_templates_exigem_token(path):
    with TestClient(app) as http:
        assert http.get(path).status_code == 401
