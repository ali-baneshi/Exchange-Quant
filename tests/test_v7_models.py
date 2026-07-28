import math
from dataclasses import FrozenInstanceError

import pytest

from exchange_q.domain import FeatureWindow
from exchange_q.models import ModelArtifact, NormalizedBornModel


def _feature(imbalance=0.0, buy_ratio=0.5):
    return FeatureWindow(
        start_ms=1,
        end_ms=2,
        trade_count=20,
        buy_count=round(20 * buy_ratio),
        sell_count=20 - round(20 * buy_ratio),
        buy_ratio=buy_ratio,
        signed_imbalance=imbalance,
        spread=0.001,
        volatility=0.01,
    )


def test_normalized_born_is_finite_and_normalized():
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.5, 1.0, 0.0, 1.0), 10)
    for imbalance in (-1.0, -0.5, 0.0, 0.5, 1.0):
        forecast = model.predict(_feature(imbalance), artifact)
        assert math.isfinite(forecast.probability_buy)
        assert 0.0 <= forecast.probability_buy <= 1.0
        diagnostics = forecast.diagnostics
        assert math.isclose(
            diagnostics["buy_mass"] / diagnostics["normalization"],
            forecast.raw_probability_buy,
            abs_tol=1e-12,
        )


def test_signed_imbalance_changes_prediction_direction():
    model = NormalizedBornModel()
    artifact = ModelArtifact(model.model_id, (0.0, 0.0, 2.0, 0.0, 1.0), 10)
    bearish = model.predict(_feature(-0.8), artifact).probability_buy
    neutral = model.predict(_feature(0.0), artifact).probability_buy
    bullish = model.predict(_feature(0.8), artifact).probability_buy
    assert bearish < neutral < bullish


def test_fit_produces_reproducible_artifact():
    features = [_feature(-0.8, 0.3), _feature(-0.4, 0.4), _feature(0.4, 0.6), _feature(0.8, 0.7)]
    buys = [30, 40, 60, 70]
    totals = [100, 100, 100, 100]
    model = NormalizedBornModel()
    first = model.fit(features, buys, totals)
    second = model.fit(features, buys, totals)
    assert first.artifact_hash == second.artifact_hash
    assert "development_prior_v1" in first.baseline_map
    assert "regularized_logistic_v1" in first.baseline_map
    forecast = model.predict(features[-1], first)
    assert set(forecast.diagnostics["baseline_probabilities"]) == {
        "development_prior_v1",
        "flow_persistence_v1",
        "regularized_logistic_v1",
    }


def test_artifact_identity_cannot_be_mutated():
    artifact = ModelArtifact(
        "model",
        (1.0,),
        1,
        baseline_parameters=(("baseline", (0.5,)),),
    )
    original_hash = artifact.artifact_hash
    with pytest.raises(FrozenInstanceError):
        artifact.parameters = (2.0,)
    assert artifact.artifact_hash == original_hash
