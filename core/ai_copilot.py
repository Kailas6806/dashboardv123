"""
V12 PRO MAX — AI Copilot & Trade Execution
Uses NVIDIA Nemotron (via integrate.api.nvidia.com) with reasoning capabilities
to perform deep multi-factor options market analysis, validate signals,
and execute algorithmic / 1-click paper trades.
"""
import json
import re
import datetime
from typing import Any, Dict, List, Optional, Tuple
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    OpenAI = None
    HAS_OPENAI = False

from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    NVIDIA_API_KEY,
    NVIDIA_BASE_URL,
    NVIDIA_MODEL,
    IST,
    MIN_ENTRY_PRICE,
    NO_NEW_TRADE_TIME,
    MAX_DAILY_TRADES,
    AI_MIN_CONVICTION,
    INDEX_CONFIG,
    is_expiry_day,
)

try:
    from utils.logger import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler())
            logger.setLevel(logging.INFO)
        return logger

log = get_logger("ai_copilot")


class AICopilot:
    """Intelligent trading analyst and execution manager powered by ChatGPT or NVIDIA NIM."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        # Detect ChatGPT vs NVIDIA
        k = api_key or OPENAI_API_KEY or NVIDIA_API_KEY
        if (api_key and api_key.startswith("sk-")) or OPENAI_API_KEY:
            self.provider = "OpenAI ChatGPT"
            self.api_key = api_key or OPENAI_API_KEY
            self.base_url = base_url or "https://api.openai.com/v1"
            self.model = model or OPENAI_MODEL
        else:
            self.provider = "NVIDIA NIM"
            self.api_key = api_key or NVIDIA_API_KEY
            self.base_url = base_url or NVIDIA_BASE_URL
            self.model = model or NVIDIA_MODEL

        self._client: Optional[OpenAI] = None
        self._analysis_cache: Dict[str, Any] = {}
        self._init_client()

    def _init_client(self) -> None:
        """Initialize the OpenAI client pointing to OpenAI or NVIDIA NIM."""
        if not HAS_OPENAI or OpenAI is None:
            log.warning("AICopilot: openai package is not installed.")
            return
        if not self.api_key:
            log.warning("AICopilot: No API key found for %s", self.provider)
            return
        try:
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=35.0,
            )
            log.info("AICopilot initialized with %s (model: %s)", self.provider, self.model)
        except Exception as e:
            log.error("AICopilot failed to initialize %s client: %s", self.provider, e)
            self._client = None

    def is_configured(self) -> bool:
        """Check if client is configured with a valid API key."""
        return self._client is not None and bool(self.api_key)

    def analyze_market_and_signals(
        self,
        idx: str,
        md: Dict[str, Any],
        raw_signal: str,
        conf_score: int,
        active_trades_count: int = 0,
    ) -> Dict[str, Any]:
        """Perform reasoning-backed AI evaluation of the market setup and signal.

        Returns a structured dictionary with:
          - market_bias: BULLISH | BEARISH | SIDEWAYS/NEUTRAL
          - recommendation: EXECUTE_BUY_CE | EXECUTE_BUY_PE | AVOID_WAIT
          - conviction_score: 0-100
          - reasoning_summary: text
          - reasoning_content: detailed thinking process
          - key_factors: list of bullet points
          - risk_warning: string
          - suggested_strike: int
          - suggested_entry_type: CE | PE | NONE
        """
        if not self.is_configured():
            return {
                "error": "NVIDIA API key not configured or invalid.",
                "market_bias": "UNKNOWN",
                "recommendation": "AVOID_WAIT",
                "conviction_score": 0,
                "reasoning_summary": "Please configure NVIDIA_API_KEY to enable AI analysis.",
                "key_factors": [],
                "risk_warning": "AI Client Offline",
            }

        spot = md.get("spot", 0)
        atm = md.get("atm_actual", 0)
        pcr = md.get("pcr", 1.0)
        pcr_mom = md.get("pcr_momentum", "FLAT")
        vwap = md.get("vwap_proxy", spot)
        spot_vs_vwap = md.get("spot_vs_vwap", "AT VWAP")
        ce_delta = md.get("total_ce_delta", 0)
        pe_delta = md.get("total_pe_delta", 0)
        support = md.get("support", 0)
        resistance = md.get("resistance", 0)
        is_sideways = md.get("is_sideways", False)
        sideways_str = md.get("sideways_strength", "")
        atm_row = md.get("atm_row", {})
        ce_ltp = atm_row.get("CE LTP", 0) if hasattr(atm_row, "get") else 0
        pe_ltp = atm_row.get("PE LTP", 0) if hasattr(atm_row, "get") else 0

        # Check cache (30-second TTL on similar market state to prevent spamming API on fast UI refresh)
        cache_key = f"{idx}_{round(spot, 0)}_{round(pcr, 2)}_{raw_signal}"
        import time as _time
        _now_ts = _time.time()
        if hasattr(self, "_analysis_cache") and cache_key in self._analysis_cache:
            _c_time, _c_res = self._analysis_cache[cache_key]
            if _now_ts - _c_time < 30.0:
                log.info("Returning cached AI Copilot analysis for %s (age: %.1fs)", idx, _now_ts - _c_time)
                return _c_res

        prompt = f"""Analyze {idx} options setup:
- Spot: {spot:.2f} | ATM: {atm}
- ATM CE LTP: ₹{ce_ltp:.2f} | ATM PE LTP: ₹{pe_ltp:.2f}
- PCR: {pcr:.2f} ({pcr_mom}) | VWAP: {vwap:.2f} ({spot_vs_vwap})
- CE OI Delta: {ce_delta:+,} | PE OI Delta: {pe_delta:+,}
- Support: {support} | Resistance: {resistance}
- Rule Signal: {raw_signal} (Score: {conf_score}/100)

Output strict JSON:
{{
  "market_bias": "BULLISH" | "BEARISH" | "SIDEWAYS/NEUTRAL",
  "recommendation": "EXECUTE_BUY_CE" | "EXECUTE_BUY_PE" | "AVOID_WAIT",
  "conviction_score": <int 0-100>,
  "suggested_strike": {atm},
  "suggested_entry_type": "CE" | "PE" | "NONE",
  "reasoning_summary": "<concise rationale under 25 words>",
  "key_factors": ["<factor 1>", "<factor 2>"],
  "risk_warning": "<risk note>"
}}"""

        try:
            # Ultra-fast inference with ChatGPT (native JSON mode) or NVIDIA NIM
            create_params = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a fast quantitative NSE options trading AI. Output strict JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 220,
            }
            if getattr(self, "provider", "") == "OpenAI ChatGPT":
                create_params["response_format"] = {"type": "json_object"}
            else:
                create_params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

            completion = self._client.chat.completions.create(**create_params)

            msg = completion.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning_content", "") or ""

            # Parse JSON from content
            parsed = self._extract_json(content)
            if not parsed:
                parsed = {
                    "market_bias": "SIDEWAYS/NEUTRAL",
                    "recommendation": "AVOID_WAIT",
                    "conviction_score": 50,
                    "suggested_strike": atm,
                    "suggested_entry_type": "NONE",
                    "reasoning_summary": content[:300] if content else "AI response received.",
                    "key_factors": ["Unable to parse structured JSON"],
                    "risk_warning": "Verify market signals manually",
                }

            parsed["reasoning_content"] = reasoning or parsed.get("reasoning_summary", "")
            parsed["raw_content"] = content
            parsed["timestamp"] = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
            if hasattr(self, "_analysis_cache"):
                self._analysis_cache[cache_key] = (_now_ts, parsed)
            return parsed

        except Exception as e:
            # Automatic fallback to NVIDIA NIM if OpenAI quota is exhausted
            if ("insufficient_quota" in str(e) or "429" in str(e)) and getattr(self, "provider", "") == "OpenAI ChatGPT" and NVIDIA_API_KEY:
                log.warning("OpenAI quota exhausted (no credits). Falling back to NVIDIA NIM...")
                try:
                    fallback_client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY, timeout=35.0)
                    fb_comp = fallback_client.chat.completions.create(
                        model=NVIDIA_MODEL,
                        messages=[
                            {"role": "system", "content": "You are a fast quantitative NSE options trading AI. Output strict JSON only."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.1,
                        max_tokens=220,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}}
                    )
                    fb_content = fb_comp.choices[0].message.content or ""
                    parsed = self._extract_json(fb_content)
                    if parsed:
                        parsed["timestamp"] = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
                        parsed["provider"] = "NVIDIA NIM (Fallback)"
                        if hasattr(self, "_analysis_cache"):
                            self._analysis_cache[cache_key] = (_now_ts, parsed)
                        return parsed
                except Exception as fb_err:
                    log.error("NVIDIA fallback failed: %s", fb_err)

            log.error("AICopilot analysis failed: %s", e)
            return {
                "error": str(e),
                "market_bias": "UNKNOWN",
                "recommendation": "AVOID_WAIT",
                "conviction_score": 0,
                "reasoning_summary": f"Inference failed: {e}",
                "key_factors": [],
                "risk_warning": "Check API connection and quota",
            }

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Safely extract JSON object from LLM response text."""
        if not text:
            return None
        text = text.strip()
        # Clean markdown code blocks
        if "```json" in text:
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
        elif "```" in text:
            match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)

        try:
            return json.loads(text)
        except Exception:
            # Attempt to find first { and last }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except Exception:
                    pass
        return None


    def generate_autonomous_signal(self, idx: str, md: Dict[str, Any]) -> Dict[str, Any]:
        spot = md.get("spot", 0)
        atm = md.get("atm_actual", 0)
        pcr = md.get("pcr", 1.0)
        pcr_mom = md.get("pcr_momentum", "FLAT")
        vwap = md.get("vwap_proxy", spot)
        spot_vs_vwap = md.get("spot_vs_vwap", "AT VWAP")
        ce_delta = md.get("total_ce_delta", 0)
        pe_delta = md.get("total_pe_delta", 0)
        support = md.get("support", 0)
        resistance = md.get("resistance", 0)

        prompt = f'''You are a quantitative options trader analyzing {idx}.

LIVE DATA:
- Spot: {spot:.2f} | ATM Strike: {atm}
- VWAP: {vwap:.2f} (Spot is {spot_vs_vwap})
- Support: {support} | Resistance: {resistance}
- PCR: {pcr:.2f} (Trend: {pcr_mom})
- Call OI Delta: {ce_delta:+,} | Put OI Delta: {pe_delta:+,}

DECISION RULES (in order):
1. Trend Context: Is spot above or below VWAP?
2. Structure: Is spot near support (bullish) or resistance (bearish)?
3. Positioning: Is PCR rising (bullish OI bias) or falling (bearish)?
4. Confirmation: Are Call/Put OI deltas aligned with PCR trend?

CONVICTION SCORING:
- Spot above VWAP + PCR rising = +30 points (bullish bias)
- Spot below VWAP + PCR falling = +30 points (bearish bias)
- Spot holds support + Call OI increasing = +20 points (bullish)
- Spot breaks resistance + Put OI increasing = +20 points (bearish)
- Conflicting signals = -10 points each

OUTPUT (strict JSON):
{{
  "trend_bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "signal": "BUY CE" | "BUY PE" | "WAIT",
  "conviction": <0-100>,
  "reasoning": "Score breakdown + final decision"
}}

DECISION RULE:
- Score >= 60: BUY CE (bullish) or BUY PE (bearish)
- Score 30-59: WAIT (mixed signals)
- Score < 30: WAIT (no clear edge)'''

        try:
            if self._client:
                create_params = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are an elite autonomous trading AI. Output strict JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 250,
                }
                if getattr(self, "provider", "") == "OpenAI ChatGPT":
                    create_params["response_format"] = {"type": "json_object"}
                else:
                    create_params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
                completion = self._client.chat.completions.create(**create_params)
                content = completion.choices[0].message.content or ""
                parsed = self._extract_json(content)
                if parsed:
                    return parsed
            import requests
            url = f"{self.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are an elite autonomous trading AI. Output strict JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 250,
            }
            if getattr(self, "provider", "") != "OpenAI ChatGPT":
                payload["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            resp = requests.post(url, headers=headers, json=payload, timeout=25.0)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                parsed = self._extract_json(content)
                if parsed:
                    return parsed
                return {"signal": "WAIT", "conviction": 0, "reasoning": "Could not parse JSON"}
            else:
                return {"signal": "WAIT", "conviction": 0, "reasoning": f"API Error {resp.status_code}"}
        except Exception as e:
            return {"signal": "WAIT", "conviction": 0, "reasoning": str(e)}

    def chat_with_agent(self, messages: list) -> str:
        if not self.is_configured():
            return f"{self.provider} API key not configured."
        try:
            if self._client:
                create_params = {
                    "model": self.model,
                    "messages": [{"role": "system", "content": "You are V12 PRO MAX, an elite financial AI assistant. You help the user analyze stocks, debug their trading logic, and understand market trends."}] + messages,
                    "temperature": 0.4,
                    "max_tokens": 512,
                }
                if getattr(self, "provider", "") != "OpenAI ChatGPT":
                    create_params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
                completion = self._client.chat.completions.create(**create_params)
                return completion.choices[0].message.content or ""
            import requests
            url = f"{self.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": "You are V12 PRO MAX, an elite financial AI assistant. You help the user analyze stocks, debug their trading logic, and understand market trends."}] + messages,
                "temperature": 0.4,
                "max_tokens": 512,
            }
            if getattr(self, "provider", "") != "OpenAI ChatGPT":
                payload["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            resp = requests.post(url, headers=headers, json=payload, timeout=30.0)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                return f"API Error: {resp.status_code} - {resp.text}"
        except Exception as e:
            return f"Error: {str(e)}"

    def draft_swing_message(self, picks_data: list) -> str:
        """Use the Copilot to draft a Telegram message for swing trade picks."""
        if not self.is_configured() or not picks_data:
            # Fallback text if Copilot is disabled
            lines = ["🎯 **Top A+ and A Swing Picks**\n"]
            for p in picks_data:
                lines.append(f"📌 {p['Symbol']} at ₹{p['Close']} (Grade: {p['Grade']})")
                lines.append(f"🔴 SL: ₹{p['Stop_Loss']} | 🎯 T1: ₹{p['Target_1']} | T2: ₹{p['Target_2']}")
                lines.append(f"⚡ Signals: {p['Signals']}\n")
            return "\n".join(lines)
            
        prompt = (
            "You are an expert swing trading assistant. I have scanned the market and found "
            "the following top-rated stock setup(s). Draft a short, energetic, and professional Telegram alert "
            "message to share with my subscribers as a photo caption.\n\n"
            "Include the Symbol, Grade, Entry Price, Stop Loss, Target 1, Target 2, and a brief note on why based on the signals.\n"
            "Use emojis appropriately. Keep it very concise since it will be an image caption.\n\n"
            f"Data: {json.dumps(picks_data, indent=2)}"
        )
        
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a professional trading bot writing Telegram alerts."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=350,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.error("Failed to draft swing message: %s", e)
            lines = ["🎯 **Top A+ and A Swing Picks**\n"]
            for p in picks_data:
                lines.append(f"📌 {p['Symbol']} at ₹{p['Close']} (Grade: {p['Grade']})")
                lines.append(f"🔴 SL: ₹{p['Stop_Loss']} | 🎯 T1: ₹{p['Target_1']} | T2: ₹{p['Target_2']}")
                lines.append(f"⚡ Signals: {p['Signals']}\n")
            return "\n".join(lines)

    def take_trade(
        self,
        idx: str,
        signal_type: str,
        md: Dict[str, Any],
        trade_mgr: Any,
        risk_mgr: Any,
        journal: Any,
        tlog: List[Dict[str, Any]],
        ai_conviction: int = 80,
        ai_reasoning: str = "AI Confirmed Setup",
        force: bool = False,
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Execute a trade into the active trade log and journal with risk controls.

        Parameters
        ----------
        idx : str
            Index name ("NIFTY", "BANKNIFTY", "FINNIFTY")
        signal_type : str
            "BUY CE" or "BUY PE"
        md : dict
            Current market data computed by SignalEngine
        trade_mgr : TradeManager
        risk_mgr : RiskManager
        journal : TradeJournal
        tlog : list
            Active session trade log for this index
        ai_conviction : int
        ai_reasoning : str
        force : bool
            If True, skips non-critical warnings (like low price or minor cooldown)

        Returns
        -------
        (success: bool, trade_entry: dict | None, message: str)
        """
        now = datetime.datetime.now(IST)
        now_time = now.time()

        # 1. Guards
        if not force:
            if now_time >= NO_NEW_TRADE_TIME:
                return False, None, f"Blocked: Past no-new-trade cutoff ({NO_NEW_TRADE_TIME.strftime('%I:%M %p')})"

            today_str = now.strftime("%Y-%m-%d")
            closed_today = 0
            if journal:
                closed_today = len(journal.get_trades_for_date(today_str))
            open_count = len([t for t in tlog if t.get("Status") == "OPEN"])
            if (closed_today + open_count) >= MAX_DAILY_TRADES:
                return False, None, f"Blocked: Daily max trades limit ({MAX_DAILY_TRADES}) reached"

        atm = md.get("atm_actual", 0)
        atm_row = md.get("atm_row", {})
        spot = md.get("spot", 0)
        lot = INDEX_CONFIG.get(idx, {}).get("lot", 50)

        # 2. Get entry price from option chain
        if signal_type == "BUY CE":
            ep = float(atm_row.get("CE LTP", 0)) if hasattr(atm_row, "get") else 0.0
        elif signal_type == "BUY PE":
            ep = float(atm_row.get("PE LTP", 0)) if hasattr(atm_row, "get") else 0.0
        else:
            return False, None, f"Invalid signal type: {signal_type}"

        expiry_today = is_expiry_day(idx)
        if ep < MIN_ENTRY_PRICE and not expiry_today and not force:
            return False, None, f"Blocked: Premium ₹{ep:.2f} is below minimum ₹{MIN_ENTRY_PRICE}"

        if ep <= 0:
            return False, None, f"Blocked: Invalid option premium ₹{ep:.2f}"

        # 3. Calculate ATR SL, Target, and Quantity
        spot_history = md.get("spot_history", [spot])
        qty, sl_p, tgt_p, ml, tp = risk_mgr.calc_trade_with_atr(ep, lot, spot_history)

        now_str = now.strftime("%I:%M:%S %p")

        # 4. Construct Trade Entry
        trade_entry = {
            "Entry Time": now_str,
            "Exit Time": None,
            "Index": idx,
            "Signal": signal_type,
            "Spot": round(spot, 2),
            "Strike": atm,
            "Entry Price": ep,
            "Live Price": ep,
            "Exit Price": None,
            "Stop Loss": sl_p,
            "Target": tgt_p,
            "Qty": qty,
            "Max Loss ₹": ml,
            "Target P&L ₹": tp,
            "Actual P&L ₹": None,
            "Status": "OPEN",
            "Result": "⏳ OPEN",
            "Confidence Score": ai_conviction,
            "_ai_generated": True,
            "_ai_conviction": ai_conviction,
            "_ai_reasoning": ai_reasoning,
            "_profit_locked": False,
            "_locked_profit": 0,
            "_peak_price": ep,
        }

        # 5. Insert into trade log & save
        tlog.insert(0, trade_entry)
        trade_mgr.save_log(idx, tlog)

        # 6. Record in Trade Journal
        if journal:
            try:
                journal_id = journal.record_trade(
                    trade_entry,
                    {
                        "pcr": md.get("pcr"),
                        "vwap": md.get("vwap_proxy"),
                        "oi_delta_ce": md.get("total_ce_delta"),
                        "oi_delta_pe": md.get("total_pe_delta"),
                        "confidence_score": ai_conviction,
                        "pcr_momentum": md.get("pcr_momentum"),
                        "ai_generated": True,
                        "ai_reasoning": ai_reasoning,
                    },
                )
                trade_entry["_journal_id"] = journal_id
            except Exception as e:
                log.warning("Journal recording error: %s", e)

        # 7. Telegram alert
        try:
            if hasattr(trade_mgr, "notifier") and trade_mgr.notifier:
                trade_mgr.notifier.send_signal_alert(
                    idx=idx,
                    signal=f"🤖 [AI] {signal_type}",
                    strike=atm,
                    spot=round(spot, 2),
                    entry=ep,
                    sl=sl_p,
                    tgt=tgt_p,
                    qty=qty,
                    ml=ml,
                    tp=tp,
                    conf="HIGH" if ai_conviction >= AI_MIN_CONVICTION else "MEDIUM",
                    score=ai_conviction,
                    time_str=now_str,
                )
        except Exception as e:
            log.warning("Telegram notification failed: %s", e)

        log.info(
            "AI TRADE EXECUTED: %s %s @ Strike %d | EP=%.2f SL=%.2f TGT=%.2f Qty=%d Conviction=%d",
            idx,
            signal_type,
            atm,
            ep,
            sl_p,
            tgt_p,
            qty,
            ai_conviction,
        )

        return True, trade_entry, f"AI Trade {signal_type} {atm} executed at Rs. {ep:.2f}!"
