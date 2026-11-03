"""Permissões finas por empresa (PORTAL_CLIENTE.md, seção 11).

No Auth0 todos os usuários do portal têm o perfil `cliente` (`read:self`/`write:self`); o que cada um pode
fazer dentro da empresa fica em `company_members.permissoes` e é aplicado pelos back-ends.
"""
from typing import Iterable

# Permissões (strings fixas do contrato, na ordem canônica usada nas respostas)
VER_FINANCEIRO = "ver_financeiro"
PAGAR = "pagar"
APROVAR_PAGAMENTOS = "aprovar_pagamentos"
PEDIR_CREDITO = "pedir_credito"
CONTRATAR_CREDITO = "contratar_credito"
GERENCIAR_ESTOQUE = "gerenciar_estoque"
GERENCIAR_EQUIPE = "gerenciar_equipe"
USAR_ASSISTENTE = "usar_assistente"

PERMISSOES: tuple[str, ...] = (
    VER_FINANCEIRO,
    PAGAR,
    APROVAR_PAGAMENTOS,
    PEDIR_CREDITO,
    CONTRATAR_CREDITO,
    GERENCIAR_ESTOQUE,
    GERENCIAR_EQUIPE,
    USAR_ASSISTENTE,
)

# Pseudo-permissão usada só no 403 de ações exclusivas do dono ({"error":"SEM_PERMISSAO","permissao":"dono"})
DONO_PERMISSAO = "dono"

# Papéis
DONO = "DONO"
ADMIN = "ADMIN"
FINANCEIRO = "FINANCEIRO"
OPERADOR = "OPERADOR"
LEITURA = "LEITURA"
PAPEIS: tuple[str, ...] = (DONO, ADMIN, FINANCEIRO, OPERADOR, LEITURA)

# Status do membro
CONVIDADO = "CONVIDADO"
ATIVO = "ATIVO"
SUSPENSO = "SUSPENSO"
STATUSES: tuple[str, ...] = (CONVIDADO, ATIVO, SUSPENSO)

PRESETS: dict[str, tuple[str, ...]] = {
    DONO: PERMISSOES,
    ADMIN: PERMISSOES,
    FINANCEIRO: (VER_FINANCEIRO, PAGAR, APROVAR_PAGAMENTOS, PEDIR_CREDITO, USAR_ASSISTENTE),
    OPERADOR: (VER_FINANCEIRO, PAGAR, GERENCIAR_ESTOQUE, USAR_ASSISTENTE),
    LEITURA: (VER_FINANCEIRO,),
}


def canonical(permissoes: Iterable[str]) -> list[str]:
    """Remove duplicadas e desconhecidas e ordena na ordem canônica de PERMISSOES."""
    granted = set(permissoes or ())
    return [p for p in PERMISSOES if p in granted]


def unknown(permissoes: Iterable[str]) -> list[str]:
    """Permissões fora da lista fixa (para o 422)."""
    return sorted(set(permissoes or ()) - set(PERMISSOES))


def preset(papel: str) -> list[str]:
    return list(PRESETS[papel])


def effective(papel: str, permissoes: Iterable[str] | None) -> list[str]:
    """Permissões efetivas: o DONO tem sempre todas (inclusive as que forem criadas depois)."""
    if papel == DONO:
        return list(PERMISSOES)
    return canonical(permissoes or ())
