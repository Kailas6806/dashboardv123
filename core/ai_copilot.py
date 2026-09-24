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
    """Intelligent trading analyst and execution manager powered by NVIDIA NIM."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or NVIDIA_API_KEY
        self.base_url = base_url or NVIDIA_BASE_URL
        self.model = model or NVIDIA_MODEL
        self._client: Optional[OpenAI] = None
        self._init_client()

    def _init_client(self) -> None:
        """Initialize the OpenAI client pointing to NVIDIA NIM."""
        if not HAS_OPENAI or OpenAI is None:
            log.warning("AICopilot: openai package is not installed.")
            return
        if not self.api_key:
            log.warning("AICopilot: No NVIDIA_API_KEY found")
            return
        try:
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=15.0,
            )
            log.info("AICopilot initialized with model %s", self.model)
        except Exception as e:
            log.error("AICopilot failed to initialize client: %s", e)
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

        prompt = f"""
You are an expert quantitative Indian index options trader for the National Stock Exchange (NSE).
Analyze the current live market setup and rule-engine signal for {idx}:

### CURRENT MARKET METRICS:
- Index: {idx}
- Spot Price: {spot:.2f}
- ATM Strike: {atm}
- ATM CE LTP: ₹{ce_ltp:.2f} | ATM PE LTP: ₹{pe_ltp:.2f}
- Put-Call Ratio (PCR): {pcr:.2f} (Momentum: {pcr_mom})
- VWAP Proxy: {vwap:.2f} (Spot is currently {spot_vs_vwap} VWAP)
- Total CE OI Delta: {ce_delta:+,} | Total PE OI Delta: {pe_delta:+,}
- Key Support: {support} | Key Resistance: {resistance}
- Market State: {"SIDEWAYS (" + sideways_str + ")" if is_sideways else "TRENDING/ACTIVE"}
- Current Algorithmic Signal: {raw_signal} (Rule Engine Score: {conf_score}/100)
- Active Open Trades in Portfolio: {active_trades_count}

### YOUR TASK:
1. Cross-examine the options open interest dynamics, VWAP relation, and potential bull/bear trap zones.
2. Determine whether the algorithmic signal ({raw_signal}) is a high-probability opportunity or a trap to avoid.
3. Provide your final trade decision.

Respond strictly in valid JSON with this exact schema:
{{
  "market_bias": "BULLISH" | "BEARISH" | "SIDEWAYS/NEUTRAL",
  "recommendation": "EXECUTE_BUY_CE" | "EXECUTE_BUY_PE" | "AVOID_WAIT",
  "conviction_score": <integer from 0 to 100>,
  "suggested_strike": <int strike price or {atm}>,
  "suggested_entry_type": "CE" | "PE" | "NONE",
  "reasoning_summary": "<concise 2-3 sentence executive summary explaining your rationale>",
  "key_factors": ["<factor 1>", "<factor 2>", "<factor 3>"],
  "risk_warning": "<key risk or stop loss warning>"
}}
"""

        try:
            # Call with reasoning enabled
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an elite institutional options trader on NSE. Output only valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2048,
                extra_body={"chat_template_kwargs": {"enable_thinking": True}},
            )

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

            parsed["reasoning_content"] = reasoning
            parsed["raw_content"] = content
            parsed["timestamp"] = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
            return parsed

        except Exception as e:
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
        
        prompt = f"""
You are an autonomous quantitative Indian index options trader. I am giving you raw live market data for {idx}. 
You must independently decide the best immediate trade (BUY CE, BUY PE, or WAIT).

### LIVE DATA:
- Spot: {spot:.2f}
- ATM Strike: {atm}
- PCR: {pcr:.2f} (Trend: {pcr_mom})
- VWAP Proxy: {vwap:.2f} (Spot is {spot_vs_vwap} VWAP)
- CE OI Delta (Call Writing): {ce_delta:+,}
- PE OI Delta (Put Writing): {pe_delta:+,}
- Support: {support} | Resistance: {resistance}

Based purely on this data, output your trading decision in strict JSON:
{{
  "market_bias": "BULLISH" | "BEARISH" | "SIDEWAYS/NEUTRAL",
  "autonomous_signal": "BUY CE" | "BUY PE" | "WAIT",
  "conviction": <0-100 integer>,
  "logic": "<Concise 2 sentence reason>"
}}
"""
        try:
            import requests
            url = f"{NVIDIA_BASE_URL}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are an elite autonomous trading AI. Output strict JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 200
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=60.0)
            if resp.status_code == 200:
                import json
                content = resp.json()["choices"][0]["message"]["content"]
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].strip()
                return json.loads(content)
            else:
                return {"autonomous_signal": "WAIT", "conviction": 0, "logic": f"API Error {resp.status_code}"}
        except Exception as e:
            return {"autonomous_signal": "WAIT", "conviction": 0, "logic": str(e)}

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
