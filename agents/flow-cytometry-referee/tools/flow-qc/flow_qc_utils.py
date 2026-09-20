"""Utilities for technical quality review of standard FCS flow-cytometry files.

The functions in this module intentionally report measurement and metadata facts.
They do not assign cell types, make clinical predictions, or validate a laboratory assay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from flowio import FlowData
from sklearn.ensemble import IsolationForest


def load_fcs(path: str | Path) -> tuple[dict[str, Any], pd.DataFrame]:
    """Read an FCS file into metadata and an events-by-channel DataFrame."""
    flow_data = FlowData(str(path))
    channel_numbers = sorted(flow_data.channels, key=lambda value: int(value))
    channel_names = [
        flow_data.channels[number].get("PnN") or f"channel_{number}"
        for number in channel_numbers
    ]
    event_count = int(flow_data.event_count)
    channel_count = len(channel_names)
    events = np.asarray(flow_data.events, dtype=float).reshape(event_count, channel_count)
    metadata = {str(key): value for key, value in flow_data.text.items()}
    metadata["_channel_ranges"] = {
        name: flow_data.channels[number].get("PnR")
        for name, number in zip(channel_names, channel_numbers, strict=True)
    }
    return metadata, pd.DataFrame(events, columns=channel_names)


def _compensation_present(metadata: dict[str, Any]) -> bool:
    normalized_keys = {key.lower().replace("$", "") for key in metadata}
    return any(key in normalized_keys for key in ("spillover", "spill", "compensation", "comp"))


def _channel_summary(events: pd.DataFrame, ranges: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for name in events.columns:
        values = events[name].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        channel_range = ranges.get(name)
        try:
            upper_limit = float(channel_range)
        except (TypeError, ValueError):
            upper_limit = None
        saturation_fraction = (
            float(np.mean(finite >= upper_limit)) if upper_limit and finite.size else None
        )
        summaries.append(
            {
                "channel": name,
                "finite_fraction": float(np.mean(np.isfinite(values))),
                "minimum": float(np.min(finite)) if finite.size else None,
                "p01": float(np.percentile(finite, 1)) if finite.size else None,
                "median": float(np.median(finite)) if finite.size else None,
                "p99": float(np.percentile(finite, 99)) if finite.size else None,
                "maximum": float(np.max(finite)) if finite.size else None,
                "saturation_fraction": saturation_fraction,
            }
        )
    return summaries


def _outlier_summary(events: pd.DataFrame, random_state: int = 0) -> dict[str, Any]:
    """Return an unsupervised event-outlier metric, never a biological classification."""
    numeric = events.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan).dropna(axis=0)
    if len(numeric) < 100 or numeric.shape[1] == 0:
        return {"available": False, "reason": "Need at least 100 complete numeric events."}
    sample = numeric.iloc[: min(len(numeric), 50_000), : min(numeric.shape[1], 16)]
    standardized = (sample - sample.median()) / sample.std(ddof=0).replace(0, 1)
    model = IsolationForest(contamination="auto", random_state=random_state, n_estimators=100)
    labels = model.fit_predict(standardized)
    return {
        "available": True,
        "events_scored": int(len(sample)),
        "channels_scored": list(sample.columns),
        "outlier_fraction": float(np.mean(labels == -1)),
        "interpretation": "Unusual multichannel measurement events, not cell identities or sample classes.",
    }


def build_qc_report(metadata: dict[str, Any], events: pd.DataFrame) -> dict[str, Any]:
    """Create a JSON-serializable, evidence-only FCS technical QC report."""
    time_columns = [name for name in events.columns if name.lower() in {"time", "acquisition_time"}]
    time_integrity: dict[str, Any] = {"available": bool(time_columns)}
    if time_columns:
        values = events[time_columns[0]].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        time_integrity.update(
            {
                "channel": time_columns[0],
                "nondecreasing_fraction": float(np.mean(np.diff(finite) >= 0)) if len(finite) > 1 else None,
                "negative_fraction": float(np.mean(finite < 0)) if len(finite) else None,
            }
        )
    return {
        "scope": "Technical FCS quality checks only; not biological, clinical, or regulatory validation.",
        "event_count": int(len(events)),
        "channel_count": int(events.shape[1]),
        "channels": list(events.columns),
        "compensation_metadata_present": _compensation_present(metadata),
        "time_integrity": time_integrity,
        "channel_summaries": _channel_summary(events, metadata.get("_channel_ranges", {})),
        "outlier_summary": _outlier_summary(events),
        "limitations": [
            "FCS metadata cannot establish that compensation was correct or that controls were appropriate.",
            "Gate quality requires the gating plan and control evidence in addition to event measurements.",
        ],
    }
