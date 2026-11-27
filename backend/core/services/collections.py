from __future__ import annotations

from decimal import Decimal
from typing import Any

COLLECTION_TONES = ("friendly", "firm", "negotiation")


def _fmt_brl(amount: Decimal) -> str:
    formatted = f"{abs(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def build_collection_message(
    *,
    tone: str,
    contact_name: str,
    company_name: str,
    invoices: list[dict[str, Any]],
) -> str:
    """Generates a deterministic collection message grounded strictly in verified open invoices."""
    total_open = sum((Decimal(str(inv["amount"])) for inv in invoices), Decimal("0.00"))
    first_due = next((inv["due"] for inv in invoices if inv.get("due")), None)
    labels = ", ".join(inv["label"] for inv in invoices[:3])
    if len(invoices) > 3:
        labels += f" e mais {len(invoices) - 3}"

    due_text = f" (vencimento principal em {first_due})" if first_due else ""
    total_text = _fmt_brl(total_open)

    if tone == "firm":
        intro = (
            f"Prezado(a) {contact_name}, identificamos pendência referente a {labels}{due_text} "
            f"com a empresa {company_name}."
        )
        closing = "Solicitamos a regularização do valor em aberto o quanto antes."
    elif tone == "negotiation":
        intro = (
            f"Olá, {contact_name}. Aqui é da equipe financeira da {company_name}, "
            f"referente a {labels}{due_text}."
        )
        closing = "Podemos combinar uma nova data ou parcelamento para facilitar a quitação?"
    else:
        intro = (
            f"Olá, {contact_name}! Tudo bem? Passando da {company_name} para lembrar "
            f"sobre {labels}{due_text}."
        )
        closing = "Podemos confirmar a previsão de pagamento?"

    return f"{intro} Valor em aberto: {total_text}. {closing}"
