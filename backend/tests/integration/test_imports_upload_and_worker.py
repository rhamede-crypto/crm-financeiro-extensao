from __future__ import annotations

import io
import time

import openpyxl
import pytest
import xlwt
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from adapters.queue.tasks import process_import_job


def _auth_client(tmp_path, settings, email: str = "etl@example.test") -> APIClient:
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    client = APIClient()
    client.post(
        "/api/v1/auth/register",
        {"name": "Operador", "email": email, "password": "Sintetico-123"},
        format="json",
    )
    client.post(
        "/api/v1/company",
        {"name": "Empresa Planilhas", "segment": "comercio_local"},
        format="json",
    )
    return client


def _build_xlsx(rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_xls(rows: list[list[object]]) -> bytes:
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Lancamentos")
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            ws.write(r_idx, c_idx, val)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.django_db
def test_imports_options_and_upload_for_csv_xlsx_xls_and_cashflow_alias(tmp_path, settings) -> None:
    client = _auth_client(tmp_path, settings)

    options = client.get("/api/v1/imports/options")
    assert options.status_code == 200
    assert options.json()["extensions"] == ["csv", "xlsx", "xls"]
    assert options.json()["maxRows"] == 10000

    sample_rows = [
        ["id", "data", "valor", "descricao", "cliente", "status", "vencimento"],
        [
            "F-1",
            "2026-10-01",
            "845.00",
            "Venda Balcao",
            "Mercado Horizonte",
            "Aberto",
            "2026-10-30",
        ],
    ]

    csv_res = client.post(
        "/api/v1/imports",
        {
            "type": "receivable",
            "file": SimpleUploadedFile(
                "receber.csv",
                b"id,data,valor,descricao,cliente,status,vencimento\n"
                b"F-1,2026-10-01,845.00,Venda Balcao,Mercado Horizonte,Aberto,2026-10-30\n",
                content_type="text/csv",
            ),
        },
        format="multipart",
    )
    assert csv_res.status_code == 202
    assert csv_res.json()["rowCount"] == 1
    assert csv_res.json()["uploadDurationMs"] >= 1
    assert csv_res.json()["processingDurationMs"] >= 1

    xlsx_res = client.post(
        "/api/v1/imports",
        {
            "type": "payable",
            "file": SimpleUploadedFile(
                "pagar.xlsx",
                _build_xlsx(sample_rows),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
        format="multipart",
    )
    assert xlsx_res.status_code == 202
    assert xlsx_res.json()["rowCount"] == 1

    xls_res = client.post(
        "/api/v1/imports",
        {
            "type": "cashflow",
            "file": SimpleUploadedFile(
                "caixa.xls",
                _build_xls(sample_rows),
                content_type="application/vnd.ms-excel",
            ),
        },
        format="multipart",
    )
    assert xls_res.status_code == 202
    assert xls_res.json()["type"] == "settled"
    assert xls_res.json()["rowCount"] == 1

    # Safe worker retry on same job does not duplicate or corrupt state
    job_id = xls_res.json()["id"]
    from adapters.persistence.models import ImportJobRecord

    job_obj = ImportJobRecord.unscoped.get(id=job_id)
    retry_out = process_import_job.run(str(job_obj.company_id), str(job_obj.id))
    assert retry_out["status"] == job_obj.status


@pytest.mark.django_db
def test_upload_rejects_malformed_empty_and_over_limit_files(tmp_path, settings) -> None:
    client = _auth_client(tmp_path, settings, email="badfiles@example.test")

    bad_ext = client.post(
        "/api/v1/imports",
        {
            "type": "receivable",
            "file": SimpleUploadedFile("virus.exe", b"MZ...", "application/octet-stream"),
        },
        format="multipart",
    )
    assert bad_ext.status_code == 422

    spoofed_xlsx = client.post(
        "/api/v1/imports",
        {
            "type": "receivable",
            "file": SimpleUploadedFile("falso.xlsx", b"nao-eh-zip", "application/octet-stream"),
        },
        format="multipart",
    )
    assert spoofed_xlsx.status_code == 422

    header_only = client.post(
        "/api/v1/imports",
        {
            "type": "receivable",
            "file": SimpleUploadedFile("vazio.csv", b"data,valor,descricao\n", "text/csv"),
        },
        format="multipart",
    )
    assert header_only.status_code == 422

    lines = ["id,data,valor,descricao"] + [
        f"L-{i},2026-10-01,10.00,Item {i}" for i in range(10_001)
    ]
    too_many = client.post(
        "/api/v1/imports",
        {
            "type": "settled",
            "file": SimpleUploadedFile("grande.csv", "\n".join(lines).encode("utf-8"), "text/csv"),
        },
        format="multipart",
    )
    assert too_many.status_code == 422


@pytest.mark.django_db
def test_benchmark_10000_rows_finishes_well_under_30_seconds(tmp_path, settings) -> None:
    client = _auth_client(tmp_path, settings, email="bench@example.test")
    lines = ["id,data,valor,descricao,cliente,status"] + [
        f"LOTE-{i},2026-10-01,125.00,Lancamento {i},Cliente Sintetico,Pago"
        for i in range(10_000)
    ]
    payload = "\n".join(lines).encode("utf-8")

    started = time.perf_counter()
    response = client.post(
        "/api/v1/imports",
        {
            "type": "settled",
            "file": SimpleUploadedFile("dez-mil.csv", payload, content_type="text/csv"),
        },
        format="multipart",
    )
    total_elapsed_s = time.perf_counter() - started

    assert response.status_code == 202
    data = response.json()
    assert data["rowCount"] == 10_000
    assert total_elapsed_s < 30.0
    print(
        f"[BE04 BENCHMARK 10k rows] total={total_elapsed_s:.3f}s "
        f"uploadMs={data['uploadDurationMs']} procMs={data['processingDurationMs']}"
    )
