"""
V12 PRO MAX — Signal Audit & Rejection Intelligence Logger
Thread-safe persistence and querying for multi-factor signal audits,
AI conviction scores, and trade rejection rationale.
"""
import os
import json
import time
import datetime
import threading
from typing import Dict, Any, List, Optional

import config
from config import INDEX_CONFIG, IST, LOG_DIR
from utils.logger import get_logger

logger = get_logger("signal_audit")


class SignalAuditor:
    """Thread-safe manager for recording and querying signal audit events."""

    def __init__(self, audit_file: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._audit_file = audit_file or os.path.join(LOG_DIR, "signal_audit.jsonl")
        self._audit_history: List[Dict[str, Any]] = []
        self._last_audit_times: Dict[str, float] = {idx: 0.0 for idx in INDEX_CONFIG}
        self._last_audit_signals: Dict[str, str] = {idx: "" for idx in INDEX_CONFIG}
        self._load_initial_audit_log()

    def _load_initial_audit_log(self) -> None:
        """Load recent audit records from disk on startup."""
        if not os.path.exists(self._audit_file):
            return
        try:
            entries = []
            with open(self._audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            continue
            with self._lock:
                self._audit_history = entries[-2000:]
            logger.info("Loaded %d signal audit records from disk", len(self._audit_history))
        except Exception as e:
            logger.warning("Error loading signal audit log: %s", e)

    def log_event(
        self,
        idx: str,
        spot: float,
        md: Dict[str, Any],
        raw_signal: str,
        final_signal: str,
        final_conf: str,
        conf_score: int,
        ai_score: Optional[int],
        ai_rec: str,
        ai_reasoning: str,
        status: str,
        rejection_code: str,
        rejection_detail: str,
        now_ist: datetime.datetime,
        force_log: bool = False,
    ) -> None:
        """Record an evaluated signal and rejection/execution details."""
        now_ts = time.time()
        last_t = self._last_audit_times.get(idx, 0.0)
        last_sig = self._last_audit_signals.get(idx, "")

        # Throttle: Log if signal changed, if executed, or if > 60s has elapsed
        if not force_log and status != "EXECUTED":
            if final_signal == last_sig and (now_ts - last_t) < 60.0:
                return

        self._last_audit_times[idx] = now_ts
        self._last_audit_signals[idx] = final_signal

        entry = {
            "timestamp": now_ist.strftime("%Y-%m-%d %I:%M:%S %p"),
            "date": now_ist.strftime("%Y-%m-%d"),
            "time_str": now_ist.strftime("%I:%M:%S %p"),
            "idx": idx,
            "spot": round(float(spot), 2),
            "atm": int(md.get("atm_actual", 0)),
            "pcr": round(float(md.get("pcr", 1.0)), 2),
            "pcr_mom": md.get("pcr_momentum", "FLAT"),
            "spot_vs_vwap": md.get("spot_vs_vwap", ""),
            "vwap": round(float(md.get("vwap_proxy", spot)), 2),
            "support": int(md.get("support", 0)),
            "resistance": int(md.get("resistance", 0)),
            "ce_delta": int(md.get("total_ce_delta", 0)),
            "pe_delta": int(md.get("total_pe_delta", 0)),
            "tot_ce": int(md.get("tot_ce", 0)),
            "tot_pe": int(md.get("tot_pe", 0)),
            "raw_signal": raw_signal,
            "final_signal": final_signal,
            "final_conf": final_conf,
            "rule_score": int(conf_score),
            "ai_conviction": int(ai_score) if ai_score is not None else None,
            "ai_rec": ai_rec,
            "status": status,  # "EXECUTED" | "REJECTED" | "NEUTRAL_WAIT"
            "rejection_code": rejection_code,
            "rejection_detail": rejection_detail,
            "ai_reasoning": ai_reasoning,
        }

        with self._lock:
            self._audit_history.append(entry)
            if len(self._audit_history) > 2000:
                self._audit_history = self._audit_history[-2000:]

        try:
            os.makedirs(os.path.dirname(self._audit_file), exist_ok=True)
            with open(self._audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning("Error persisting signal audit entry: %s", e)

    def get_audit_log(
        self,
        limit: int = 1000,
        idx: Optional[str] = None,
        filter_status: Optional[str] = None,
        date_str: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return slice of audit log filtered by date, index, or status."""
        with self._lock:
            records = list(self._audit_history)
        if date_str and date_str != "ALL":
            records = [r for r in records if (r.get("date") or str(r.get("timestamp", ""))[:10]) == date_str]
        if idx and idx != "ALL":
            records = [r for r in records if r.get("idx") == idx]
        if filter_status and filter_status != "ALL":
            records = [r for r in records if r.get("status") == filter_status or r.get("rejection_code") == filter_status]
        return records[-limit:][::-1]  # Most recent first

    def get_audit_stats(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """Return summary statistics across the audit history, optionally filtered by date."""
        with self._lock:
            records = list(self._audit_history)
        if date_str and date_str != "ALL":
            records = [r for r in records if (r.get("date") or str(r.get("timestamp", ""))[:10]) == date_str]
        total = len(records)
        executed = sum(1 for r in records if r.get("status") == "EXECUTED")
        rejected = sum(1 for r in records if r.get("status") == "REJECTED")
        neutral = sum(1 for r in records if r.get("status") == "NEUTRAL_WAIT")

        reasons: Dict[str, int] = {}
        for r in records:
            rc = r.get("rejection_code")
            if rc and rc not in ("NONE", "NO_SETUP"):
                reasons[rc] = reasons.get(rc, 0) + 1
        return {
            "total_setups": total,
            "executed": executed,
            "rejected": rejected,
            "neutral_wait": neutral,
            "rejection_breakdown": reasons,
        }


# Singleton factory
_auditor_lock = threading.Lock()
_global_auditor: Optional[SignalAuditor] = None


def get_signal_auditor() -> SignalAuditor:
    global _global_auditor
    if _global_auditor is None:
        with _auditor_lock:
            if _global_auditor is None:
                _global_auditor = SignalAuditor()
    return _global_auditor
