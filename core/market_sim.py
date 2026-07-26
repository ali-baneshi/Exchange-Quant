#!/usr/bin/env python3

"""
Synthetic market simulator with hidden context.

Creates agents whose decisions are modulated by an unobserved hidden variable,
producing non-classical (quantum-like) correlations.  Used by experiment.py
to compare classical and Born-rule predictions in a controlled setting.

Note: history entries include a synthetic `imbalance` derived from buy_ratio.
That is NOT a real order book — it only exercises the same feature key the
live pipeline uses so compute_delta / Born rule share one code path.

Usage:
    sim = MarketSimulator(n_agents=30, seed=42)
    for t in range(500):
        sim.step(hidden_context)
"""

import math
import random
import statistics

from quantum_core import born_rule_predict


class Agent:
    def __init__(self, agent_id, base_bias=0.0):
        self.id = agent_id
        self.base_bias = base_bias
        self.position = 0.0

    def decide(self, price_change, hidden_context):
        """
        Decision depends on price change AND hidden context.
        hidden_context creates the 'disjunction' — the agent acts
        differently when context is known vs unknown.
        """
        contextual_amp = math.sin(price_change + self.base_bias + hidden_context)
        sigmoid = 1 / (1 + math.exp(-3 * contextual_amp))
        return 1 if random.random() < sigmoid else 0


class MarketSimulator:
    """
    A synthetic market where agents make buy(1)/sell(0) decisions.
    A hidden context variable creates non-classical correlations.
    """
    def __init__(self, n_agents=50, price_volatility=0.5, seed=42):
        random.seed(seed)
        self.n_agents = n_agents
        self.vol = price_volatility
        self.price = 100.0
        self.agents = [Agent(i, base_bias=random.uniform(-0.5, 0.5)) for i in range(n_agents)]
        self.history = []

    def step(self, hidden_context):
        """
        Run one time step.
        hidden_context: a float that modulates ALL agents' decisions
        """
        price_change = random.gauss(0, self.vol)
        self.price += price_change

        decisions = [a.decide(price_change, hidden_context) for a in self.agents]
        buy_ratio = sum(decisions) / self.n_agents

        self.history.append({
            'price': self.price,
            'price_change': price_change,
            'hidden_context': hidden_context,
            'buy_ratio': buy_ratio,
            'buy_count': sum(decisions),
            # Synthetic proxy only — not a real L2 order-book imbalance.
            'imbalance': 2.0 * (buy_ratio - 0.5),
            'volatility': abs(price_change) / max(self.price, 0.001),
        })
        return self.history[-1]

    def run_episode(self, n_steps=200, context_switch_prob=0.02):
        """
        Run many steps. hidden_context switches between values
        (creating different regimes that classical models miss).
        """
        hidden_context = 0.0
        for _ in range(n_steps):
            if random.random() < context_switch_prob:
                hidden_context = random.choice([-1.5, 0.0, 1.5])
            self.step(hidden_context)
        return self.history


def classical_model(history_lookback):
    """
    Uses the law of total probability on recent data.
    Always predicts the average of recent buy ratios.
    """
    ratios = [h['buy_ratio'] for h in history_lookback]
    return statistics.mean(ratios) if ratios else 0.5


def quantum_model(history_lookback, delta=None):
    """
    Born-rule prediction via quantum_core (single source of truth).

    If delta is provided, it overrides compute_delta (synthetic probes only).
    """
    pred, _ = born_rule_predict(
        history_lookback,
        delta_override=delta if delta is not None else None,
    )
    return pred


def quantum_model_diagnostic(history_lookback, delta=None):
    """
    Same prediction as quantum_model plus split / hidden-context diagnostics.
    """
    pred, meta = born_rule_predict(
        history_lookback,
        delta_override=delta if delta is not None else None,
    )

    ratios = [h['buy_ratio'] for h in history_lookback]
    if len(history_lookback) < 4:
        return pred, {"fallback": meta.get("fallback_reason", "insufficient_history"),
                      "n": len(history_lookback)}

    median = statistics.median(ratios)
    high_context = [h for h in history_lookback if h['buy_ratio'] > median]
    low_context = [h for h in history_lookback if h['buy_ratio'] <= median]
    high_hidden = [h.get('hidden_context', 0) for h in high_context]
    low_hidden = [h.get('hidden_context', 0) for h in low_context]

    diag = {
        "fallback": meta.get("fallback_reason", "none"),
        "n_high": len(high_context),
        "n_low": len(low_context),
        "mu_high": meta.get("mu_high"),
        "mu_low": meta.get("mu_low"),
        "p_high": meta.get("p_high"),
        "p_low": meta.get("p_low"),
        "mean_hidden_high": statistics.mean(high_hidden) if high_hidden else 0,
        "mean_hidden_low": statistics.mean(low_hidden) if low_hidden else 0,
        "hidden_separation": (
            abs(statistics.mean(high_hidden) - statistics.mean(low_hidden))
            if high_hidden and low_hidden else 0
        ),
        "delta": meta.get("delta"),
        "delta_source": meta.get("delta_source"),
    }
    return pred, diag
