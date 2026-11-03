"""Templates de onboarding por segmento: dados versionados no código (PORTAL_CLIENTE.md, seção 3).

Os ids comuns são iguais em todos os segmentos: o Score (KPIs) e o seeder do Transactions leem estas
chaves de ``respostas``. Não renomeie um id sem avisar as outras sessões.
"""

VERSAO = "2026-11-03"

SAZONALIDADE = ["Baixa", "Média", "Alta"]


def _campo(id_, label, tipo, obrigatorio=False, **extra):
    campo = {"id": id_, "label": label, "tipo": tipo, "obrigatorio": obrigatorio}
    campo.update(extra)
    return campo


# --- campos comuns (todos os segmentos) -------------------------------------------------------------
FATURAMENTO = _campo("faturamento_mensal", "Faturamento médio mensal", "currency", True,
                     ajuda="Média dos últimos 12 meses, antes de impostos.")
MARGEM = _campo("margem_bruta_pct", "Margem bruta média", "percent", True,
                ajuda="(Receita − custo do que foi vendido) ÷ receita.")
SAZONAL = _campo("sazonalidade", "Sazonalidade das vendas", "select", True, opcoes=SAZONALIDADE,
                 ajuda="Quanto o faturamento varia ao longo do ano.")
PMR = _campo("prazo_medio_recebimento_dias", "Prazo médio de recebimento (dias)", "integer", True,
             min=0, max=365, ajuda="Em quantos dias, em média, o dinheiro das vendas entra no caixa.")
PMP = _campo("prazo_medio_pagamento_dias", "Prazo médio de pagamento a fornecedores (dias)", "integer",
             True, min=0, max=365)
FOLHA = _campo("folha_mensal", "Folha de pagamento mensal", "currency", True,
               ajuda="Salários, pró-labore e encargos.")
POSSUI_ESTOQUE = _campo("possui_estoque", "Trabalha com estoque?", "boolean", True)
VALOR_ESTOQUE = _campo("valor_estoque", "Valor atual do estoque (a custo)", "currency",
                       ajuda="Obrigatório quando trabalha com estoque.")
DIVIDAS = _campo("dividas_total", "Total de dívidas e empréstimos", "currency", True,
                 ajuda="Saldo devedor somado de empréstimos, financiamentos e parcelamentos.")
PARCELAS = _campo("parcela_dividas_mensal", "Parcelas de dívidas por mês", "currency", True)

# --- campos reutilizados em mais de um segmento ------------------------------------------------------
TICKET = _campo("ticket_medio", "Ticket médio por venda", "currency")
CARTAO = _campo("pct_cartao_credito", "% das vendas no cartão de crédito", "percent", True)


def _template(segmento, nome, descricao, icone, vendas=(), operacao=()):
    """Monta as 3 seções padrão; os campos específicos entram em vendas e operação."""
    return {
        "segmento": segmento,
        "versao": VERSAO,
        "nome": nome,
        "descricao": descricao,
        "icone": icone,
        "secoes": [
            {"id": "vendas", "titulo": "Como você vende",
             "campos": [FATURAMENTO, MARGEM, SAZONAL, *vendas]},
            {"id": "operacao", "titulo": "Operação",
             "campos": [*operacao, PMR, PMP, FOLHA, POSSUI_ESTOQUE, VALOR_ESTOQUE]},
            {"id": "financeiro", "titulo": "Financeiro", "campos": [DIVIDAS, PARCELAS]},
        ],
    }


TEMPLATES = [
    _template(
        "varejo", "Varejo e e-commerce", "Lojas físicas e online", "store",
        vendas=[
            CARTAO,
            _campo("parcelamento_medio", "Parcelamento médio (vezes)", "number", min=1, max=24),
            _campo("canais", "Canais de venda", "multiselect",
                   opcoes=["Loja física", "E-commerce próprio", "Marketplace", "Redes sociais"]),
            TICKET,
        ],
    ),
    _template(
        "alimentacao", "Alimentação", "Bares, restaurantes e food service", "utensils",
        vendas=[
            TICKET,
            CARTAO,
            _campo("pct_delivery", "% das vendas por delivery", "percent"),
        ],
        operacao=[
            _campo("tipo_estabelecimento", "Tipo de estabelecimento", "select", True,
                   opcoes=["Restaurante", "Bar", "Lanchonete", "Padaria e confeitaria",
                           "Food service e dark kitchen"]),
        ],
    ),
    _template(
        "servicos", "Serviços", "Agências, consultorias, escritórios e prestadores", "briefcase",
        vendas=[
            TICKET,
            CARTAO,
            _campo("pct_receita_recorrente", "% da receita recorrente (contratos mensais)", "percent"),
        ],
        operacao=[
            _campo("tipo_servico", "Tipo de serviço", "select", True,
                   opcoes=["Consultoria", "Marketing e agência", "Contabilidade e jurídico",
                           "Educação e treinamento", "Manutenção e serviços técnicos", "Outros serviços"]),
        ],
    ),
    _template(
        "saude", "Saúde", "Clínicas, consultórios e laboratórios", "stethoscope",
        vendas=[
            TICKET,
            CARTAO,
            _campo("pct_convenios", "% da receita vinda de convênios", "percent",
                   ajuda="Convênios costumam pagar em 30 a 90 dias."),
        ],
        operacao=[
            _campo("tipo_estabelecimento", "Tipo de estabelecimento", "select", True,
                   opcoes=["Clínica médica", "Clínica odontológica", "Consultório", "Laboratório",
                           "Estética", "Fisioterapia e reabilitação"]),
        ],
    ),
    _template(
        "tecnologia", "Tecnologia", "SaaS, software e serviços digitais", "code",
        vendas=[
            _campo("mrr", "Receita recorrente mensal (MRR)", "currency", True),
            _campo("churn_mensal_pct", "Churn mensal", "percent",
                   ajuda="% dos clientes ou do MRR perdido por mês."),
            _campo("cac", "Custo de aquisição de cliente (CAC)", "currency"),
            _campo("modelo_receita", "Modelo de receita", "select", True,
                   opcoes=["Assinatura (SaaS)", "Licença", "Projetos e consultoria", "Transacional"]),
        ],
    ),
    _template(
        "industria", "Indústria", "Fabricação e transformação", "factory",
        vendas=[
            _campo("pct_maior_cliente", "% do faturamento no maior cliente", "percent",
                   ajuda="Mede a concentração da receita."),
            _campo("pct_exportacao", "% do faturamento com exportação", "percent"),
        ],
        operacao=[
            _campo("setor_industrial", "Setor", "select", True,
                   opcoes=["Alimentos e bebidas", "Têxtil e confecção", "Metalmecânica",
                           "Química e plásticos", "Móveis e madeira", "Outro setor"]),
            _campo("capacidade_utilizada_pct", "Capacidade produtiva utilizada", "percent"),
        ],
    ),
    _template(
        "agro", "Agronegócio", "Produtores rurais, cooperados e pecuária", "wheat",
        vendas=[
            _campo("safra_principal", "Cultura ou atividade principal", "select", True,
                   opcoes=["Soja", "Milho", "Café", "Cana-de-açúcar", "Algodão", "Pecuária",
                           "Hortifrúti", "Outra"]),
            _campo("canal_comercializacao", "Para quem vende", "select",
                   opcoes=["Cooperativa", "Trading", "Agroindústria", "Venda direta"]),
            _campo("mes_colheita", "Mês principal de colheita ou venda (1 a 12)", "integer",
                   min=1, max=12),
        ],
        operacao=[
            _campo("area_hectares", "Área produtiva (hectares)", "number", True, min=0),
        ],
    ),
    _template(
        "construcao", "Construção", "Construtoras, empreiteiras e reformas", "hard-hat",
        vendas=[
            _campo("tipo_obra", "Tipo de obra predominante", "select", True,
                   opcoes=["Residencial", "Comercial", "Infraestrutura", "Reformas"]),
            _campo("carteira_contratada", "Carteira de obras contratada (a executar)", "currency"),
            _campo("pct_contratos_publicos", "% da receita com contratos públicos", "percent"),
        ],
        operacao=[
            _campo("obras_em_andamento", "Obras em andamento", "integer", min=0),
        ],
    ),
    _template(
        "outro", "Outro segmento", "Não encontrou o seu? Conte como é o negócio", "circle-help",
        vendas=[TICKET, CARTAO],
        operacao=[
            _campo("descricao_atividade", "O que a empresa faz", "text", True, max=500,
                   ajuda="Produtos ou serviços, quem são os clientes e como você vende."),
        ],
    ),
]
