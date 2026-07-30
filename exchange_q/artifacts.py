from __future__ import annotations

import json
import os

from exchange_q.models import ModelArtifact


def save_artifact(path: str, artifact: ModelArtifact) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "model_id": artifact.model_id,
                "parameters": artifact.parameters,
                "development_rows": artifact.development_rows,
                "calibration_intercept": artifact.calibration_intercept,
                "calibration_slope": artifact.calibration_slope,
                "baseline_parameters": artifact.baseline_parameters,
                "purpose": artifact.purpose,
                "dataset_hash": artifact.dataset_hash,
                "fitting_revision": artifact.fitting_revision,
                "feature_policy": artifact.feature_policy,
                "label_policy": artifact.label_policy,
                "development_start_ms": artifact.development_start_ms,
                "development_end_ms": artifact.development_end_ms,
                "calibration_rows": artifact.calibration_rows,
                "calibration_status": artifact.calibration_status,
            },
            handle,
            indent=2,
            sort_keys=True,
        )
    os.replace(temporary, path)


def load_artifact(path: str) -> ModelArtifact:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["parameters"] = tuple(payload["parameters"])
    payload["baseline_parameters"] = tuple(
        (name, tuple(parameters)) for name, parameters in payload.get("baseline_parameters", ())
    )
    return ModelArtifact(**payload)
