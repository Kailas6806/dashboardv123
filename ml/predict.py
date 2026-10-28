import datetime
from config import IST
from ml.model_manager import predict_live_observer_probability


def observe_ml_signal(
    idx: str,
    signal: str,
    md: dict,
    strategy_score: float,
    ai_analysis: dict = None,
):
    """
    Return an evaluation-only live probability, or None when no compatible model exists.
    """
    return predict_live_observer_probability(
        idx,
        signal,
        md,
        datetime.datetime.now(IST),
        strategy_score,
        ai_analysis=ai_analysis,
    )
