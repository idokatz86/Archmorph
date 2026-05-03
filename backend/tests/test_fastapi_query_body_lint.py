import textwrap

from scripts.lint_fastapi_query_body_tests import Route, scan_file


def test_query_only_route_rejects_json_body(tmp_path):
    test_file = tmp_path / "test_e2e.py"
    test_file.write_text(
        textwrap.dedent(
            """
            def test_export(client, diagram_id):
                client.post(f"/api/diagrams/{diagram_id}/export-diagram", json={"format": "drawio"})
            """
        ),
        encoding="utf-8",
    )
    route = Route(
        "POST",
        "/api/diagrams/{diagram_id}/export-diagram",
        ("POST", "/api/diagrams/{}/export-diagram"),
    )

    violations = scan_file(test_file, {route.key: route})

    assert len(violations) == 1
    assert "replace json= with params=" in violations[0].render()


def test_query_only_route_allows_params(tmp_path):
    test_file = tmp_path / "test_e2e.py"
    test_file.write_text(
        textwrap.dedent(
            """
            def test_export(client, diagram_id):
                client.post(f"/api/diagrams/{diagram_id}/export-diagram", params={"format": "drawio"})
            """
        ),
        encoding="utf-8",
    )
    route = Route(
        "POST",
        "/api/diagrams/{diagram_id}/export-diagram",
        ("POST", "/api/diagrams/{}/export-diagram"),
    )

    assert scan_file(test_file, {route.key: route}) == []


def test_body_route_allows_json_body(tmp_path):
    test_file = tmp_path / "test_apply_answers.py"
    test_file.write_text(
        textwrap.dedent(
            """
            def test_apply_answers(client, diagram_id):
                client.post(f"/api/diagrams/{diagram_id}/apply-answers", json={"answers": {}})
            """
        ),
        encoding="utf-8",
    )

    assert scan_file(test_file, {}) == []
