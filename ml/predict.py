import datetime
from config import IST
from ml.model_manager import predict_live_observer_probability


def observe_ml_signal(
    idx: str,
    signal: str,
    md: dict,
    strategy_score: float,
    ai_analysis: dict = None,
    entry_price: float = None,
    stop_loss: float = None,
    buffer_state: list = None,
):
    """
    Return an evaluation-only live probability, or None when no compatible model exists.
    """
    return predict_live_observer_probability(
        idx=idx,
        signal=signal,
        market_data=md,
        now=datetime.datetime.now(IST),
        confidence_score=strategy_score,
        entry_price=entry_price,
        stop_loss=stop_loss,
        buffer_state=buffer_state,
        ai_analysis=ai_analysis,
    )
