from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core.services.etl import propose_column_mapping


def _to_csv(rows: list[list[object]], sep: str = ",") -> bytes:
    return "\n".join(sep.join(str(cell) for cell in row) for row in rows).encode("utf-8")


@pytest.mark.django_db
def test_mapping_validation_set_exceeds_80_percent_without_intervention(tmp_path, settings) -> None:
    """BE05: Measures >= 80% automatic mapping accuracy on a 12-file synthetic set."""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    validation_cases = [
        (
            "01_padrao.csv",
            [
                ["id", "data", "valor", "descricao", "cliente", "status", "vencimento"],
                ["1", "2026-10-01", "100.00", "Venda", "Cliente A", "Pago", "2026-10-10"],
            ],
            True,
        ),
        (
            "02_erp_br.csv",
            [
                [
                    "documento",
                    "dt emissao",
                    "vlr liquido",
                    "historico",
                    "sacado",
                    "situacao",
                    "dt vencimento",
                ],
                ["2", "01/10/2026", "250,00", "Servico", "Cliente B", "Aberto", "15/10/2026"],
            ],
            True,
        ),
        (
            "03_fornecedor.xlsx",
            [
                [
                    "nf",
                    "competencia",
                    "valor total",
                    "discriminacao",
                    "fornecedor",
                    "estado",
                    "vencto",
                ],
                [
                    "NF-9",
                    "2026-10-02",
                    "420.00",
                    "Embalagens",
                    "Distribuidora Aurora",
                    "Aberto",
                    "2026-10-20",
                ],
            ],
            True,
        ),
        (
            "04_caixa.xls",
            [
                ["codigo", "data lancamento", "montante", "lancamento", "contraparte", "status"],
                ["C-1", "2026-10-03", "95.50", "Caixa Dia", "Balcao", "Pago"],
            ],
            True,
        ),
        (
            "05_minimo.csv",
            [
                ["data", "valor", "descricao"],
                ["2026-10-04", "150.00", "Aluguel"],
            ],
            True,
        ),
        (
            "06_acentos.csv",
            [
                [
                    "Referência",
                    "Emissão",
                    "Valor R$",
                    "Descrição",
                    "Razão Social",
                    "Situação",
                    "Vencimento",
                ],
                [
                    "R-1",
                    "2026-10-05",
                    "780.00",
                    "Mensalidade",
                    "Mercado Horizonte",
                    "Aberto",
                    "2026-10-25",
                ],
            ],
            True,
        ),
        (
            "07_pagar.xlsx",
            [
                [
                    "identificador",
                    "data pagamento",
                    "valor original",
                    "detalhes",
                    "favorecido",
                    "status",
                    "vcto",
                ],
                ["P-1", "2026-10-06", "310.00", "Energia", "Concessionaria", "Pago", "2026-10-06"],
            ],
            True,
        ),
        (
            "08_receber.xls",
            [
                [
                    "nosso numero",
                    "data emissao",
                    "quantia",
                    "titulo",
                    "pagador",
                    "status",
                    "data vencto",
                ],
                [
                    "NN-1",
                    "2026-10-07",
                    "600.00",
                    "Fatura",
                    "Padaria Central",
                    "Aberto",
                    "2026-10-30",
                ],
            ],
            True,
        ),
        (
            "09_simples.csv",
            [
                ["dt", "vlr", "item", "contato"],
                ["2026-10-08", "89.90", "Cafe", "Fornecedor X"],
            ],
            True,
        ),
        (
            "10_comercial.xlsx",
            [
                [
                    "doc",
                    "data de emissao",
                    "preco",
                    "referente a",
                    "nome cliente",
                    "data de vencimento",
                ],
                ["D-10", "2026-10-09", "1200.00", "Pedido 10", "Mercado Sul", "2026-11-09"],
            ],
            True,
        ),
        (
            "11_revisao_livre.csv",
            [
                ["id", "data", "Cobrado", "Descrição livre", "cliente"],
                ["1", "2026-10-10", "125.00", "Livre", "Cliente Z"],
            ],
            False,
        ),
        (
            "12_incompleto.csv",
            [
                ["data", "origem", "observacao"],
                ["2026-10-11", "sintetico", "sem valor"],
            ],
            False,
        ),
    ]

    auto_ok = 0
    review_required = 0
    for filename, table, expected_auto in validation_cases:
        proposal = propose_column_mapping(table)
        is_auto = not proposal.needs_review
        assert is_auto is expected_auto, (
            f"Unexpected review decision for {filename}: {proposal.mapping}"
        )
        if is_auto:
            auto_ok += 1
        else:
            review_required += 1

    total = len(validation_cases)
    accuracy = auto_ok / total
    assert accuracy >= 0.80
    print(f"[BE05 ACCURACY] auto={auto_ok}/{total} ({accuracy:.1%}), review={review_required}")

    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Rev", "email": "rev@example.test", "password": "Sintetico-123"},
        format="json",
    )
    client.post("/api/v1/company", {"name": "Empresa Revisao"}, format="json")

    ambiguous_res = client.post(
        "/api/v1/imports",
        {
            "type": "receivable",
            "file": SimpleUploadedFile(
                "revisao.csv",
                _to_csv(validation_cases[10][1]),
                content_type="text/csv",
            ),
        },
        format="multipart",
    )
    assert ambiguous_res.status_code == 202
    job = ambiguous_res.json()
    assert job["status"] == "review"
    assert job["mapping"]["amount"] == {"column": "", "confidence": "low"}
    assert job["mapping"]["description"]["confidence"] == "low"
    assert len(job["fields"]) == 7
    assert len(job["preview"]) == 1
