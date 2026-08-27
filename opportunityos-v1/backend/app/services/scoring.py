WEIGHTS = {
    "icp_fit": 0.25,
    "buying_signal_strength": 0.25,
    "signal_recency": 0.15,
    "problem_relevance": 0.15,
    "decision_maker_access": 0.10,
    "growth_momentum": 0.10,
}

def weighted_score(parts: dict[str, float]) -> int:
    return round(sum(parts[k] * WEIGHTS[k] for k in WEIGHTS))
