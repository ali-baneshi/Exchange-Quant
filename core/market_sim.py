#!/usr/bin/env python3

"""
Synthetic market simulator with hidden context.

Creates agents whose decisions are modulated by an unobserved hidden variable,
producing non-classical (quantum-like) correlations.  Used by experiment.py
to compare classical and Born-rule predictions in a controlled setting.

Usage:
    sim = MarketSimulator(n_agents=30, seed=42)
    for t in range(500):
        sim.step(hidden_context)
"""

import math
import random
import statistics
import cmath


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

    Classical can only do: P(buy) ≈ rolling_average
    No way to account for unobserved context.
    """
    ratios = [h['buy_ratio'] for h in history_lookback]
    return statistics.mean(ratios) if ratios else 0.5


def quantum_model(history_lookback, delta=math.pi):
    """
    Uses Born rule with interference.

    Splits recent history into two 'context groups' based on
    whether buy_ratio was above or below median, then applies
    the Born rule with an interference phase.

    This captures non-classical correlations that classical
    averaging misses.
    """
    if len(history_lookback) < 4:
        return 0.5

    ratios = [h['buy_ratio'] for h in history_lookback]
    median = statistics.median(ratios)

    high_context = [r for r in ratios if r > median]
    low_context = [r for r in ratios if r <= median]

    if not high_context or not low_context:
        return statistics.mean(ratios)

    p_high = len(high_context) / len(ratios)
    p_low = len(low_context) / len(ratios)

    mu_high = statistics.mean(high_context)
    mu_low = statistics.mean(low_context)

    amp_high = math.sqrt(p_high * mu_high)
    amp_low = math.sqrt(p_low * mu_low) * cmath.exp(1j * delta)

    total = amp_high + amp_low
    quantum_pred = abs(total) ** 2
    return max(0, min(1, quantum_pred))
