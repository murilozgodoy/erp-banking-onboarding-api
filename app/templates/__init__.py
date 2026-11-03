"""Templates de onboarding por segmento e validação das respostas.

API pública (outros módulos dependem dela; mantenha as assinaturas):
``SEGMENTOS``, ``list_templates()``, ``get_template(segmento)`` e ``validate_respostas(segmento, respostas)``.
"""
from copy import deepcopy

from app.templates.data import TEMPLATES, VERSAO
from app.templates.validation import validate_template_respostas

__all__ = ["SEGMENTOS", "VERSAO", "get_template", "list_templates", "validate_respostas"]

_BY_SEGMENTO: dict[str, dict] = {t["segmento"]: t for t in TEMPLATES}

SEGMENTOS: tuple[str, ...] = tuple(_BY_SEGMENTO)


def list_templates() -> list[dict]:
    """Todos os templates, na ordem de exibição (cópias: o chamador pode alterá-las)."""
    return deepcopy(TEMPLATES)


def get_template(segmento: str) -> dict | None:
    template = _BY_SEGMENTO.get(segmento)
    return deepcopy(template) if template is not None else None


def validate_respostas(segmento: str, respostas: dict) -> list[dict]:
    """Erros ``[{"campo", "erro"}]`` das respostas ao template do segmento; lista vazia quando válido."""
    template = _BY_SEGMENTO.get(segmento)
    if template is None:
        return [{"campo": "segmento", "erro": f"Segmento desconhecido: {segmento!r}."}]
    return validate_template_respostas(template, respostas)
