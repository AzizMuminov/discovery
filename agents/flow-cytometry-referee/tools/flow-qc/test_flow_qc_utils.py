"""End-to-end tests for the flow-cytometry QC helper."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from flowio import create_fcs

sys.path.insert(0, str(Path(__file__).parent))
from flow_qc_utils import build_qc_report, load_fcs, write_qc_artifacts


def test_load_fcs_preserves_channel_names_and_time_qc(tmp_path: Path) -> None:
    """A generated standards-compliant FCS file retains names needed by technical checks."""
    destination = tmp_path / "synthetic.fcs"
    rng = np.random.default_rng(42)
    events = np.column_stack(
        (
            rng.normal(50_000, 5_000, 500),
            rng.normal(20_000, 3_000, 500),
            np.arange(500),
            rng.uniform(0, 60_000, 500),
        )
    ).astype("float32")
    with destination.open("wb") as handle:
        create_fcs(
            handle,
            events.flatten().tolist(),
            ["FSC-A", "SSC-A", "Time", "FITC-A"],
            metadata_dict={"$SPILLOVER": "synthetic"},
        )

    metadata, parsed_events = load_fcs(destination)
    report = build_qc_report(metadata, parsed_events)

    assert parsed_events.columns.tolist() == ["FSC-A", "SSC-A", "Time", "FITC-A"]
    assert report["event_count"] == 500
    assert report["compensation_metadata_present"] is True
    assert report["time_integrity"]["available"] is True
    assert report["outlier_summary"]["available"] is True
    assert json.dumps(report)


def test_write_qc_artifacts_creates_dashboard_and_csv(tmp_path: Path) -> None:
    events = pd.DataFrame(
        {"FSC-A": [100, 200, 300], "SSC-A": [20, 30, 40], "Time": [0, 1, 2], "FITC-A": [10, 30, 20]}
    )
    report = build_qc_report({"_channel_ranges": {}}, events)
    artifacts = write_qc_artifacts(report, events, tmp_path, "fixture")
    assert Path(artifacts["qc_dashboard"]).read_bytes().startswith(b"\x89PNG")
    assert Path(artifacts["channel_summary_csv"]).is_file()
