from __future__ import annotations

import json

from exchange_q.models import ModelArtifact


def save_artifact(path: str, artifact: ModelArtifact) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "model_id": artifact.model_id,
                "parameters": artifact.parameters,
                "development_rows": artifact.development_rows,
                "calibration_intercept": artifact.calibration_intercept,
                "calibration_slope": artifact.calibration_slope,
                "baseline_parameters": artifact.baseline_parameters,
            },
            handle,
            indent=2,
            sort_keys=True,
        )


def load_artifact(path: str) -> ModelArtifact:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["parameters"] = tuple(payload["parameters"])
    payload["baseline_parameters"] = tuple(
        (name, tuple(parameters))
        for name, parameters in payload.get("baseline_parameters", ())
    )
    return ModelArtifact(**payload)
