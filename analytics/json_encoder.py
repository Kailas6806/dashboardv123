"""JSON encoder for values commonly produced by the trading data pipeline."""

import datetime
import json
from typing import Any


class NpEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()

        try:
            import numpy as np
        except ImportError:
            return super().default(obj)

        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return obj.item()
        return super().default(obj)
