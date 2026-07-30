"""Adversarial durable-export scanning and private Blob contracts."""

from __future__ import annotations

import io
import base64
import zipfile
from types import SimpleNamespace

import pytest

from artifact_blob_store import (
    ArtifactBlobStoreError,
    InvalidArtifactBlobReference,
    build_artifact_reference,
    delete_artifact_blob,
    parse_artifact_reference,
)
from error_envelope import ArchmorphException
from export_content_scanner import scan_generated_export


def _zip(members: dict[str, bytes], *, encrypted: set[str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if encrypted and name in encrypted:
                info.flag_bits |= 0x1
            archive.writestr(info, content)
    return buffer.getvalue()


def _error_code(exc_info) -> str:
    return exc_info.value.details["error"]


def test_non_utf8_secret_is_rejected():
    content = "token=abcdefghijklmnopqrstuvwxyz123456".encode("utf-16")
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(content, format="txt")
    assert _error_code(exc_info) == "artifact_secret_detected"


def test_zip_member_secret_is_rejected():
    content = _zip({"safe/readme.txt": b"password=abcdefghijklmnopqrstuvwxyz"})
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(content, format="zip")
    assert _error_code(exc_info) == "artifact_secret_detected"


def test_nested_archive_secret_is_rejected():
    nested = _zip({"payload.txt": b"api_key=abcdefghijklmnopqrstuvwxyz"})
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(_zip({"nested.zip": nested}), format="zip")
    assert _error_code(exc_info) == "artifact_secret_detected"


@pytest.mark.parametrize(
    "name",
    ["../escape.txt", "/absolute.txt", "a/../../escape.txt", "C:/escape.txt"],
)
def test_archive_path_traversal_is_rejected(name):
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(_zip({name: b"safe"}), format="zip")
    assert _error_code(exc_info) == "artifact_archive_traversal"


def test_archive_bomb_is_rejected(monkeypatch):
    monkeypatch.setattr("export_content_scanner.MAX_COMPRESSION_RATIO", 2)
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(_zip({"large.txt": b"A" * 10000}), format="zip")
    assert _error_code(exc_info) == "artifact_archive_bomb"


def test_encrypted_archive_metadata_is_rejected(monkeypatch):
    original = zipfile.ZipFile.infolist

    def encrypted_members(self):
        members = original(self)
        members[0].flag_bits |= 0x1
        return members

    monkeypatch.setattr(zipfile.ZipFile, "infolist", encrypted_members)
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(_zip({"safe.txt": b"safe"}), format="zip")
    assert _error_code(exc_info) == "artifact_archive_encrypted"


def test_archive_depth_limit_is_rejected(monkeypatch):
    monkeypatch.setattr("export_content_scanner.MAX_ARCHIVE_DEPTH", 1)
    deepest = _zip({"safe.txt": b"safe"})
    middle = _zip({"deep.zip": deepest})
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(_zip({"middle.zip": middle}), format="zip")
    assert _error_code(exc_info) == "artifact_archive_depth_exceeded"


def test_safe_docx_style_archive_is_accepted():
    content = _zip({
        "[Content_Types].xml": b"<Types />",
        "word/document.xml": b"<document><text>safe architecture</text></document>",
    })
    scan_generated_export(content, format="docx")


def test_opaque_archive_member_fails_closed():
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(_zip({"payload.bin": b"\x00\x01\x02"}), format="zip")
    assert _error_code(exc_info) == "artifact_archive_member_unscannable"


def test_duplicate_archive_member_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("same.txt", b"safe")
        archive.writestr("same.txt", b"also safe")
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(buffer.getvalue(), format="zip")
    assert _error_code(exc_info) == "artifact_archive_duplicate_member"


def test_unsupported_opaque_binary_fails_closed():
    with pytest.raises(ArchmorphException) as exc_info:
        scan_generated_export(b"\x00\x01\x02\x03", format="bin")
    assert _error_code(exc_info) == "artifact_binary_scan_unavailable"


def test_safe_excalidraw_json_is_scanned_as_text():
    scan_generated_export(
        b'{"type":"excalidraw","version":2,"elements":[]}',
        format="excalidraw",
    )


def test_safe_png_and_pdf_are_scanned():
    from PIL import Image
    from pypdf import PdfWriter

    image_buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(image_buffer, format="PNG")
    scan_generated_export(image_buffer.getvalue(), format="png")

    pdf_buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf_buffer)
    scan_generated_export(pdf_buffer.getvalue(), format="pdf")


@pytest.mark.parametrize("format", ["docx", "pptx", "pdf"])
def test_application_generated_hld_binary_is_scannable(format):
    from hld_export import export_hld
    from tests.test_hld_export import MOCK_HLD

    payload = base64.b64decode(
        export_hld(MOCK_HLD, format, include_diagrams=False)["content_b64"]
    )
    scan_generated_export(payload, format=format)


def test_rejection_occurs_before_blob_or_sql_persistence(monkeypatch):
    from export_artifacts import persist_generated_export

    upload_called = False

    def unexpected_upload(**_kwargs):
        nonlocal upload_called
        upload_called = True

    monkeypatch.setattr("export_artifacts.get_request_durable_principal", lambda _request: {
        "owner_user_id": "owner",
        "tenant_id": "tenant",
    })
    monkeypatch.setattr("export_artifacts.has_canonical_durable_principal", lambda _request: True)
    monkeypatch.setattr("export_artifacts._upload_blob", unexpected_upload)
    with pytest.raises(ArchmorphException) as exc_info:
        persist_generated_export(
            object(),
            diagram_id="diagram",
            artifact_type="unsafe",
            format="zip",
            content=_zip({"secret.txt": b"secret=abcdefghijklmnopqrstuvwxyz"}),
            force_blob=True,
        )
    assert _error_code(exc_info) == "artifact_secret_detected"
    assert upload_called is False


def test_authenticated_public_sample_export_does_not_require_customer_version(
    monkeypatch,
):
    from export_artifacts import persist_generated_export
    from routers.shared import SESSION_STORE

    diagram_id = "sample-public-export-contract"
    SESSION_STORE.set(diagram_id, {"diagram_id": diagram_id, "is_sample": True})

    class DatabaseSession:
        def close(self):
            pass

    monkeypatch.setattr(
        "export_artifacts.get_request_durable_principal",
        lambda _request: {
            "owner_user_id": "api-key:sample",
            "tenant_id": "service:sample",
        },
    )
    monkeypatch.setattr(
        "export_artifacts.has_canonical_durable_principal",
        lambda _request: True,
    )
    monkeypatch.setattr("database.SessionLocal", DatabaseSession)
    monkeypatch.setattr(
        "workspace_store.get_current_analysis_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("sample has no customer canonical version")
        ),
    )
    try:
        assert persist_generated_export(
            object(),
            diagram_id=diagram_id,
            artifact_type="sample-report",
            format="json",
            content='{"safe": true}',
        ) is None
    finally:
        SESSION_STORE.delete(diagram_id)


def test_blob_reference_rejects_arbitrary_container_path_and_scope(monkeypatch):
    monkeypatch.setattr("artifact_blob_store.ARTIFACT_CONTAINER", "private-artifacts")
    reference = build_artifact_reference(
        owner_user_id="owner-a",
        tenant_id="tenant-a",
        analysis_id="analysis-a",
        version_id="version-a",
        artifact_type="report",
        content_hash="a" * 64,
    )
    assert parse_artifact_reference(
        reference.uri,
        owner_user_id="owner-a",
        tenant_id="tenant-a",
    ) == reference
    for invalid in (
        reference.uri.replace("private-artifacts", "foreign-container"),
        "https://127.0.0.1/private-artifacts/blob",
        "azblob://private-artifacts/../../foreign",
    ):
        with pytest.raises(InvalidArtifactBlobReference):
            parse_artifact_reference(invalid, owner_user_id="owner-a", tenant_id="tenant-a")
    with pytest.raises(InvalidArtifactBlobReference):
        parse_artifact_reference(reference.uri, owner_user_id="owner-b", tenant_id="tenant-a")


def test_blob_delete_is_idempotent_and_confirms_absence(monkeypatch):
    state = {"exists": True}

    class Blob:
        def delete_blob(self):
            state["exists"] = False

        def exists(self):
            return state["exists"]

    service = SimpleNamespace(get_blob_client=lambda **_kwargs: Blob())
    monkeypatch.setattr("artifact_blob_store.ARTIFACT_CONTAINER", "private-artifacts")
    monkeypatch.setattr("artifact_blob_store._service_client", lambda: service)
    reference = build_artifact_reference(
        owner_user_id="owner",
        tenant_id="tenant",
        analysis_id="analysis",
        version_id="version",
        artifact_type="report",
        content_hash="b" * 64,
    )
    assert delete_artifact_blob(
        reference.uri,
        owner_user_id="owner",
        tenant_id="tenant",
    ) is True

    class MissingBlob(Blob):
        def delete_blob(self):
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("missing")

    monkeypatch.setattr(
        "artifact_blob_store._service_client",
        lambda: SimpleNamespace(get_blob_client=lambda **_kwargs: MissingBlob()),
    )
    assert delete_artifact_blob(
        reference.uri,
        owner_user_id="owner",
        tenant_id="tenant",
    ) is False


def test_blob_delete_fails_closed_when_absence_check_fails(monkeypatch):
    class Blob:
        def delete_blob(self):
            return None

        def exists(self):
            raise OSError("transient")

    monkeypatch.setattr("artifact_blob_store.ARTIFACT_CONTAINER", "private-artifacts")
    monkeypatch.setattr(
        "artifact_blob_store._service_client",
        lambda: SimpleNamespace(get_blob_client=lambda **_kwargs: Blob()),
    )
    reference = build_artifact_reference(
        owner_user_id="owner",
        tenant_id="tenant",
        analysis_id="analysis",
        version_id="version",
        artifact_type="report",
        content_hash="c" * 64,
    )
    with pytest.raises(ArtifactBlobStoreError):
        delete_artifact_blob(reference.uri, owner_user_id="owner", tenant_id="tenant")