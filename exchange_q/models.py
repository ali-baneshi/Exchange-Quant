from __future__ import annotations

import cmath
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np
from scipy.optimize import minimize

from exchange_q.domain import FeatureWindow, Forecast


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _logit(probability: float) -> float:
    bounded = min(1.0 - 1e-9, max(1e-9, probability))
    return math.log(bounded / (1.0 - bounded))


@dataclass(frozen=True)
class ModelArtifact:
    model_id: str
    parameters: tuple[float, ...]
    development_rows: int
    calibration_intercept: float = 0.0
    calibration_slope: float = 1.0
    baseline_parameters: tuple[tuple[str, tuple[float, ...]], ...] = field(
        default_factory=tuple
    )

    @property
    def artifact_hash(self) -> str:
        payload = json.dumps(
            {
                "model_id": self.model_id,
                "parameters": self.parameters,
                "development_rows": self.development_rows,
                "calibration_intercept": self.calibration_intercept,
                "calibration_slope": self.calibration_slope,
                "baseline_parameters": self.baseline_parameters,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def baseline_map(self) -> dict[str, tuple[float, ...]]:
        return dict(self.baseline_parameters)


class ForecastModel(Protocol):
    model_id: str

    def fit(
        self,
        features: Sequence[FeatureWindow],
        buy_counts: Sequence[int],
        total_counts: Sequence[int],
    ) -> ModelArtifact: ...

    def predict(self, context: FeatureWindow, artifact: ModelArtifact) -> Forecast: ...


class NormalizedBornModel:
    model_id = "normalized_born_v1"

    @staticmethod
    def _raw_probability(context: FeatureWindow, parameters: Sequence[float]):
        prior_logit, flow_scale, imbalance_scale, phase_bias, phase_scale = parameters
        flow = 2.0 * context.buy_ratio - 1.0
        imbalance = context.signed_imbalance
        path_weight = _sigmoid(2.0 * imbalance)
        trend_probability = _sigmoid(
            prior_logit + flow_scale * flow + imbalance_scale * imbalance
        )
        conservative_probability = _sigmoid(
            prior_logit + flow_scale * flow + 0.25 * imbalance_scale * imbalance
        )
        phase = math.pi * _sigmoid(phase_bias - phase_scale * abs(imbalance))
        signed_phase = phase if imbalance >= 0 else math.pi - phase

        buy_amplitude = (
            math.sqrt(path_weight * trend_probability)
            + cmath.exp(1j * signed_phase)
            * math.sqrt((1.0 - path_weight) * conservative_probability)
        )
        sell_amplitude = (
            math.sqrt(path_weight * (1.0 - trend_probability))
            - cmath.exp(1j * signed_phase)
            * math.sqrt((1.0 - path_weight) * (1.0 - conservative_probability))
        )
        buy_mass = abs(buy_amplitude) ** 2
        sell_mass = abs(sell_amplitude) ** 2
        normalization = buy_mass + sell_mass
        probability = buy_mass / normalization if normalization > 0 else 0.5
        return probability, {
            "path_weight": path_weight,
            "trend_probability": trend_probability,
            "conservative_probability": conservative_probability,
            "phase": phase,
            "signed_phase": signed_phase,
            "buy_mass": buy_mass,
            "sell_mass": sell_mass,
            "normalization": normalization,
        }

    def fit(self, features, buy_counts, total_counts) -> ModelArtifact:
        if not features or len(features) != len(buy_counts) or len(features) != len(total_counts):
            raise ValueError("aligned development rows are required")
        if any(total <= 0 or buy < 0 or buy > total for buy, total in zip(buy_counts, total_counts)):
            raise ValueError("invalid binomial counts")
        prior = sum(buy_counts) / sum(total_counts)
        initial = np.array([_logit(prior), 0.5, 0.5, 0.0, 1.0], dtype=float)

        def objective(values):
            loss = 0.0
            for context, buy_count, total_count in zip(features, buy_counts, total_counts):
                probability, _ = self._raw_probability(context, values)
                probability = min(1.0 - 1e-9, max(1e-9, probability))
                loss -= buy_count * math.log(probability)
                loss -= (total_count - buy_count) * math.log(1.0 - probability)
            regularization = 0.01 * float(np.dot(values[1:], values[1:]))
            return loss + regularization

        result = minimize(objective, initial, method="L-BFGS-B")
        if not result.success or not np.all(np.isfinite(result.x)):
            raise RuntimeError(f"Born model fitting failed: {result.message}")
        baseline_parameters = (
            ("development_prior_v1", (prior,)),
            (
                "regularized_logistic_v1",
                self._fit_logistic_baseline(features, buy_counts, total_counts, prior),
            ),
        )
        return ModelArtifact(
            model_id=self.model_id,
            parameters=tuple(float(value) for value in result.x),
            development_rows=len(features),
            baseline_parameters=baseline_parameters,
        )

    def predict(self, context: FeatureWindow, artifact: ModelArtifact) -> Forecast:
        if artifact.model_id != self.model_id:
            raise ValueError("artifact does not belong to this model")
        raw_probability, diagnostics = self._raw_probability(context, artifact.parameters)
        calibrated = _sigmoid(
            artifact.calibration_intercept
            + artifact.calibration_slope * _logit(raw_probability)
        )
        diagnostics = dict(diagnostics)
        diagnostics["artifact_hash"] = artifact.artifact_hash
        baseline_map = artifact.baseline_map
        prior_parameters = baseline_map.get("development_prior_v1")
        logistic_parameters = baseline_map.get("regularized_logistic_v1")
        baselines = {"flow_persistence_v1": context.buy_ratio}
        if prior_parameters:
            baselines["development_prior_v1"] = float(prior_parameters[0])
        if logistic_parameters:
            baselines["regularized_logistic_v1"] = self._logistic_probability(
                context, logistic_parameters
            )
        diagnostics["baseline_probabilities"] = baselines
        return Forecast(
            model_id=self.model_id,
            probability_buy=calibrated,
            raw_probability_buy=raw_probability,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _logistic_probability(context: FeatureWindow, parameters: Sequence[float]) -> float:
        intercept, flow_weight, imbalance_weight, spread_weight, volatility_weight = parameters
        return _sigmoid(
            intercept
            + flow_weight * (2.0 * context.buy_ratio - 1.0)
            + imbalance_weight * context.signed_imbalance
            + spread_weight * context.spread
            + volatility_weight * context.volatility
        )

    def _fit_logistic_baseline(self, features, buy_counts, total_counts, prior):
        initial = np.array([_logit(prior), 0.0, 0.0, 0.0, 0.0], dtype=float)

        def objective(values):
            loss = 0.0
            for context, buy_count, total_count in zip(features, buy_counts, total_counts):
                probability = self._logistic_probability(context, values)
                probability = min(1.0 - 1e-9, max(1e-9, probability))
                loss -= buy_count * math.log(probability)
                loss -= (total_count - buy_count) * math.log(1.0 - probability)
            return loss + 0.05 * float(np.dot(values[1:], values[1:]))

        result = minimize(objective, initial, method="L-BFGS-B")
        if not result.success or not np.all(np.isfinite(result.x)):
            raise RuntimeError(f"Logistic baseline fitting failed: {result.message}")
        return tuple(float(value) for value in result.x)


class PriorBaseline:
    model_id = "development_prior_v1"

    def fit(self, features, buy_counts, total_counts) -> ModelArtifact:
        if not buy_counts or len(buy_counts) != len(total_counts):
            raise ValueError("aligned counts are required")
        prior = sum(buy_counts) / sum(total_counts)
        return ModelArtifact(self.model_id, (prior,), len(buy_counts))

    def predict(self, context: FeatureWindow, artifact: ModelArtifact) -> Forecast:
        probability = float(artifact.parameters[0])
        return Forecast(self.model_id, probability, probability, {"artifact_hash": artifact.artifact_hash})


class PersistenceBaseline:
    model_id = "flow_persistence_v1"

    def fit(self, features, buy_counts, total_counts) -> ModelArtifact:
        return ModelArtifact(self.model_id, (), len(features))

    def predict(self, context: FeatureWindow, artifact: ModelArtifact) -> Forecast:
        return Forecast(
            self.model_id,
            context.buy_ratio,
            context.buy_ratio,
            {"artifact_hash": artifact.artifact_hash},
        )
