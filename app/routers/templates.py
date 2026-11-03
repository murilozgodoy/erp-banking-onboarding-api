from fastapi import APIRouter, HTTPException, status

from app.templates import get_template, list_templates

router = APIRouter(prefix="/onboarding/templates", tags=["onboarding"])


@router.get("")
def get_templates() -> list[dict]:
    """Templates de onboarding por segmento (qualquer usuário autenticado)."""
    return list_templates()


@router.get("/{segmento}")
def get_segment_template(segmento: str) -> dict:
    template = get_template(segmento)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Segmento desconhecido: {segmento}")
    return template
