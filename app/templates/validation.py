"""Validação das respostas do onboarding contra um template."""
import math
from typing import Any

TEXT_MAX_LENGTH = 1000  # limite padrão de campos text sem `max`


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, list | dict) and not value


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n).replace(".", ",")


def _check_type(campo: dict, value: Any) -> str | None:
    tipo = campo["tipo"]
    if tipo in ("currency", "number", "percent"):
        if not _is_number(value):
            return "Informe um número."
        if value < 0:
            return "O valor não pode ser negativo."
        if tipo == "percent" and value > 100:
            return "Informe um percentual entre 0 e 100."
    elif tipo == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return "Informe um número inteiro."
    elif tipo == "boolean":
        if not isinstance(value, bool):
            return "Informe sim ou não."
    elif tipo == "select":
        if not isinstance(value, str) or value not in campo["opcoes"]:
            return "Escolha uma das opções: " + ", ".join(campo["opcoes"]) + "."
    elif tipo == "multiselect":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return "Envie uma lista de opções."
        invalid = [v for v in value if v not in campo["opcoes"]]
        if invalid:
            return "Opções inválidas: " + ", ".join(invalid) + "."
    elif tipo == "text":
        if not isinstance(value, str):
            return "Informe um texto."
    else:  # pragma: no cover - os testes dos templates garantem tipos conhecidos
        raise ValueError(f"tipo de campo desconhecido: {tipo}")
    return None


def _check_limits(campo: dict, value: Any) -> str | None:
    if campo["tipo"] == "text":
        limit = campo.get("max", TEXT_MAX_LENGTH)
        return f"Use no máximo {limit} caracteres." if len(value) > limit else None
    if not _is_number(value):
        return None
    if "min" in campo and value < campo["min"]:
        return f"O valor mínimo é {_fmt(campo['min'])}."
    if "max" in campo and value > campo["max"]:
        return f"O valor máximo é {_fmt(campo['max'])}."
    return None


def validate_template_respostas(template: dict, respostas: dict) -> list[dict]:
    if not isinstance(respostas, dict):
        return [{"campo": "respostas", "erro": "As respostas devem ser um objeto."}]

    campos = [campo for secao in template["secoes"] for campo in secao["campos"]]
    estoque_obrigatorio = respostas.get("possui_estoque") is True
    errors: list[dict] = []
    for campo in campos:
        value = respostas.get(campo["id"])
        required = campo.get("obrigatorio", False) or (
            campo["id"] == "valor_estoque" and estoque_obrigatorio
        )
        if _is_empty(value):
            if required:
                errors.append({"campo": campo["id"], "erro": "Campo obrigatório."})
            continue
        message = _check_type(campo, value) or _check_limits(campo, value)
        if message:
            errors.append({"campo": campo["id"], "erro": message})
    return errors
