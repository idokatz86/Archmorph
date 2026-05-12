from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import sys
import textwrap


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "mutation_score_gate.py"
SPEC = spec_from_file_location("mutation_score_gate", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
mutation_score_gate = module_from_spec(SPEC)
sys.modules[SPEC.name] = mutation_score_gate
SPEC.loader.exec_module(mutation_score_gate)


def _write_baseline(tmp_path, report="session_store.txt"):
    baseline = tmp_path / "mutation-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "minimum_score": 60,
                "modules": [
                    {
                        "name": "session_store",
                        "path": "backend/session_store.py",
                        "report": report,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return baseline


def test_mutation_gate_passes_when_score_meets_baseline(tmp_path):
    baseline = _write_baseline(tmp_path)
    report_dir = tmp_path / "mutation-results"
    report_dir.mkdir()
    (report_dir / "session_store.txt").write_text(
        textwrap.dedent(
            """
            killed: 6
            survived: 3
            timeout: 1
            incompetent: 2
            """
        ),
        encoding="utf-8",
    )

    assert mutation_score_gate.main(["--baseline", str(baseline), "--report-dir", str(report_dir)]) == 0


def test_mutation_gate_fails_when_score_drops_below_baseline(tmp_path):
    baseline = _write_baseline(tmp_path)
    report_dir = tmp_path / "mutation-results"
    report_dir.mkdir()
    (report_dir / "session_store.txt").write_text("killed: 2\nsurvived: 8\n", encoding="utf-8")

    assert mutation_score_gate.main(["--baseline", str(baseline), "--report-dir", str(report_dir)]) == 1


def test_mutation_gate_fails_when_report_is_missing(tmp_path):
    baseline = _write_baseline(tmp_path)
    report_dir = tmp_path / "mutation-results"
    report_dir.mkdir()

    assert mutation_score_gate.main(["--baseline", str(baseline), "--report-dir", str(report_dir)]) == 1


def test_mutation_gate_parses_json_module_reports(tmp_path):
    baseline = _write_baseline(tmp_path, report="summary.json")
    report_dir = tmp_path / "mutation-results"
    report_dir.mkdir()
    (report_dir / "summary.json").write_text(
        json.dumps({"modules": [{"name": "session_store", "killed": 3, "survived": 2}]}),
        encoding="utf-8",
    )

    assert mutation_score_gate.main(["--baseline", str(baseline), "--report-dir", str(report_dir)]) == 0