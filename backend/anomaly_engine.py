"""Real-time Anomaly Detection Engine for 3-Way Transaction Reconciliation.

Strategies:
1. Statistical Outlier Detection — Z-score on rolling per-(country, bank) amount stats
2. Velocity Analysis — burst detection per user in sliding windows
3. Pattern Scoring — round amounts, off-hours, first-seen entities, high-value
4. Cross-Source Reconciliation — proportional deviation, missing-source probability
5. Combined Multi-Signal Risk Scoring — weighted combination into 0-100

All computation is in-memory, zero external calls, thread-safe.
"""

from __future__ import annotations

import math
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Rolling Statistics (Welford's online algorithm with exponential decay)
# ---------------------------------------------------------------------------

class RollingStats:
    """Numerically stable online mean/variance with exponential decay."""

    __slots__ = ("count", "mean", "_m2", "_decay")

    def __init__(self, decay: float = 0.997):
        self.count: int = 0
        self.mean: float = 0.0
        self._m2: float = 0.0
        self._decay = decay

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self._m2 = self._m2 * self._decay + delta * delta2

    @property
    def variance(self) -> float:
        return self._m2 / max(self.count - 1, 1) if self.count >= 2 else 0.0

    @property
    def stddev(self) -> float:
        return math.sqrt(max(self.variance, 0.0))

    def z_score(self, value: float) -> float:
        if self.stddev < 1e-9 or self.count < 10:
            return 0.0
        return abs(value - self.mean) / self.stddev


# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    name: str
    score: float        # contribution to risk 0-100
    detail: str
    weight: float = 1.0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Velocity: max transactions per user in window
_VELOCITY_WINDOW_SEC = 60.0
_VELOCITY_BURST_THRESHOLD = 5

# Statistical: Z-score thresholds
_Z_SCORE_WARN = 2.0
_Z_SCORE_CRITICAL = 3.5

# Off-hours (UTC): transactions between 00:00-05:00 UTC are suspicious
_OFF_HOURS_START = 0
_OFF_HOURS_END = 5

# High-value thresholds per currency
_HIGH_VALUE: Dict[str, float] = {
    "INR": 200_000,
    "USD": 10_000,
    "GBP": 8_000,
    "EUR": 9_000,
    "SGD": 15_000,
    "AED": 50_000,
    "AUD": 15_000,
}

# Round amount detection
_ROUND_AMOUNT_DIVISORS = [10_000, 50_000, 100_000]

# Source arrival window for missing detection (adaptive baseline)
_DEFAULT_ARRIVAL_WINDOW_SEC = 5.0


# ---------------------------------------------------------------------------
# Main Engine
# ---------------------------------------------------------------------------

class AnomalyEngine:
    """Thread-safe, in-memory anomaly detection engine."""

    def __init__(self):
        self._lock = threading.Lock()

        # Per (country, bank) amount statistics
        self._amount_stats: Dict[str, RollingStats] = defaultdict(RollingStats)

        # Per source propagation delay stats
        self._propagation_stats: Dict[str, RollingStats] = defaultdict(RollingStats)

        # Velocity: user_id -> deque of timestamps
        self._user_velocity: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

        # First-seen tracking
        self._known_users: set = set()
        self._known_devices: set = set()

        # Source reliability tracking
        self._source_totals: Dict[str, int] = defaultdict(int)
        self._source_drops: Dict[str, int] = defaultdict(int)

        # Overall counters
        self.total_analyzed: int = 0
        self.total_anomalies: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_transaction(
        self,
        tx_id: str,
        pg: Optional[Dict],
        cbs: Optional[Dict],
        mobile: Optional[Dict],
    ) -> Dict[str, Any]:
        """Run full anomaly analysis on a reconciled transaction.

        Returns a dict compatible with the alert `ai` field:
        {
            ok: bool,
            analysis: str,
            risk_score: int,
            risk_level: str,
            signals: [{ name, score, detail }],
            recommended_action: str,
            confidence: float,
            raw: { ... },
        }
        """
        with self._lock:
            signals: List[Signal] = []
            primary = pg or cbs or mobile
            if not primary:
                return self._build_result(tx_id, signals, "No transaction data available")

            self.total_analyzed += 1

            # --- Detection strategies ---
            signals.extend(self._check_amount_outlier(primary))
            signals.extend(self._check_cross_source(pg, cbs, mobile))
            signals.extend(self._check_velocity(primary))
            signals.extend(self._check_patterns(primary))
            signals.extend(self._check_missing_sources(pg, cbs, mobile))
            signals.extend(self._check_timing(pg, cbs, mobile))

            # Update rolling statistics with this transaction
            self._update_stats(primary, pg, cbs, mobile)

            # Synthesize
            analysis = self._synthesize_analysis(signals, pg, cbs, mobile)
            result = self._build_result(tx_id, signals, analysis)

            if result["risk_score"] >= 40:
                self.total_anomalies += 1

            return result

    def get_engine_stats(self) -> Dict[str, Any]:
        """Return engine health metrics."""
        with self._lock:
            drop_rates = {}
            for src in ("pg", "cbs", "mobile"):
                total = self._source_totals.get(src, 0)
                drops = self._source_drops.get(src, 0)
                drop_rates[src] = round(drops / max(total, 1) * 100, 1)

            return {
                "total_analyzed": self.total_analyzed,
                "total_anomalies": self.total_anomalies,
                "anomaly_rate": round(self.total_anomalies / max(self.total_analyzed, 1) * 100, 1),
                "source_drop_rates": drop_rates,
                "tracked_users": len(self._known_users),
                "tracked_devices": len(self._known_devices),
            }

    # ------------------------------------------------------------------
    # Detection: Statistical Amount Outlier
    # ------------------------------------------------------------------

    def _check_amount_outlier(self, txn: Dict) -> List[Signal]:
        signals = []
        amount = txn.get("amount", 0)
        country = txn.get("country", "XX")
        bank = txn.get("bank", "UNKNOWN")
        key = f"{country}:{bank}"

        stats = self._amount_stats[key]
        if stats.count >= 10:
            z = stats.z_score(amount)
            if z >= _Z_SCORE_CRITICAL:
                signals.append(Signal(
                    name="STATISTICAL_OUTLIER",
                    score=min(95, 50 + z * 10),
                    detail=f"Amount Z-score={z:.1f} for {bank}/{country} (mean={stats.mean:.0f}, stddev={stats.stddev:.0f})",
                    weight=1.5,
                ))
            elif z >= _Z_SCORE_WARN:
                signals.append(Signal(
                    name="AMOUNT_DEVIATION",
                    score=min(60, 25 + z * 8),
                    detail=f"Amount deviates from norm: Z-score={z:.1f} for {bank}/{country}",
                    weight=1.0,
                ))
        return signals

    # ------------------------------------------------------------------
    # Detection: Cross-Source Comparison
    # ------------------------------------------------------------------

    def _check_cross_source(self, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict]) -> List[Signal]:
        signals = []
        sources = [s for s in [pg, cbs, mobile] if s]
        if len(sources) < 2:
            return signals

        # Amount comparison
        amounts = [s["amount"] for s in sources]
        if len(set(amounts)) > 1:
            max_amt = max(amounts)
            min_amt = min(amounts)
            deviation = (max_amt - min_amt) / max(min_amt, 0.01)

            if deviation > 10.0:
                signals.append(Signal(
                    name="EXTREME_AMOUNT_DEVIATION",
                    score=100,
                    detail=f"Massive cross-source amount deviation: {deviation:.0f}x ({min_amt:.2f} vs {max_amt:.2f}). Potential fraud/injection.",
                    weight=2.0,
                ))
            elif deviation > 1.0:
                signals.append(Signal(
                    name="SIGNIFICANT_AMOUNT_MISMATCH",
                    score=min(85, 40 + deviation * 15),
                    detail=f"Large amount mismatch: {deviation*100:.1f}% deviation across sources.",
                    weight=1.5,
                ))
            elif deviation > 0.05:
                signals.append(Signal(
                    name="AMOUNT_MISMATCH",
                    score=min(50, 15 + deviation * 100),
                    detail=f"Amount differs by {deviation*100:.2f}% across sources. Possible rounding/fee issue.",
                    weight=1.2,
                ))
            elif deviation > 0:
                signals.append(Signal(
                    name="MICRO_VARIANCE",
                    score=10,
                    detail=f"Tiny amount variance ({deviation*100:.3f}%). Likely rounding difference.",
                    weight=0.5,
                ))

        # Status comparison
        statuses = [s.get("status") for s in sources]
        if len(set(statuses)) > 1:
            signals.append(Signal(
                name="STATUS_MISMATCH",
                score=35,
                detail=f"Status drift across sources: {', '.join(set(statuses))}. Race condition or webhook lag.",
                weight=1.0,
            ))

        # Timestamp comparison
        timestamps = [s.get("timestamp", 0) for s in sources]
        max_drift = max(timestamps) - min(timestamps)
        if max_drift > 30.0:
            signals.append(Signal(
                name="SEVERE_TIMESTAMP_DRIFT",
                score=45,
                detail=f"Timestamp drift of {max_drift:.1f}s across sources. Severe sync issue.",
                weight=1.2,
            ))
        elif max_drift > 5.0:
            signals.append(Signal(
                name="TIMESTAMP_DRIFT",
                score=20,
                detail=f"Timestamp drift of {max_drift:.1f}s. Possible network latency.",
                weight=0.8,
            ))

        return signals

    # ------------------------------------------------------------------
    # Detection: Velocity (Burst) Analysis
    # ------------------------------------------------------------------

    def _check_velocity(self, txn: Dict) -> List[Signal]:
        signals = []
        user_id = txn.get("user_id")
        if not user_id:
            return signals

        now = time.time()
        window = self._user_velocity[user_id]
        window.append(now)

        # Count transactions in window
        cutoff = now - _VELOCITY_WINDOW_SEC
        recent = sum(1 for t in window if t > cutoff)

        if recent >= _VELOCITY_BURST_THRESHOLD * 2:
            signals.append(Signal(
                name="VELOCITY_CRITICAL",
                score=85,
                detail=f"User {user_id[:8]}... has {recent} transactions in {_VELOCITY_WINDOW_SEC:.0f}s. Highly suspicious burst.",
                weight=1.8,
            ))
        elif recent >= _VELOCITY_BURST_THRESHOLD:
            signals.append(Signal(
                name="VELOCITY_WARNING",
                score=45,
                detail=f"User {user_id[:8]}... has {recent} transactions in {_VELOCITY_WINDOW_SEC:.0f}s. Above normal rate.",
                weight=1.2,
            ))

        return signals

    # ------------------------------------------------------------------
    # Detection: Pattern Analysis
    # ------------------------------------------------------------------

    def _check_patterns(self, txn: Dict) -> List[Signal]:
        signals = []
        amount = txn.get("amount", 0)
        currency = txn.get("currency", "INR")
        user_id = txn.get("user_id", "")
        device_id = txn.get("device_id", "")

        # Round amount detection
        for divisor in _ROUND_AMOUNT_DIVISORS:
            if amount > 0 and amount % divisor == 0 and amount >= divisor:
                signals.append(Signal(
                    name="ROUND_AMOUNT",
                    score=15,
                    detail=f"Suspiciously round amount: {amount} (divisible by {divisor}).",
                    weight=0.6,
                ))
                break

        # High-value transaction
        threshold = _HIGH_VALUE.get(currency, 50_000)
        if amount > threshold:
            ratio = amount / threshold
            signals.append(Signal(
                name="HIGH_VALUE",
                score=min(50, 15 + ratio * 8),
                detail=f"High-value transaction: {amount:.2f} {currency} ({ratio:.1f}x threshold).",
                weight=1.0,
            ))

        # Off-hours transaction (UTC)
        hour = time.gmtime().tm_hour
        if _OFF_HOURS_START <= hour < _OFF_HOURS_END:
            signals.append(Signal(
                name="OFF_HOURS",
                score=20,
                detail=f"Transaction at {hour}:00 UTC (off-hours window {_OFF_HOURS_START}-{_OFF_HOURS_END} UTC).",
                weight=0.7,
            ))

        # First-seen user (new entity with no history)
        if user_id and user_id not in self._known_users:
            if amount > threshold * 0.5:
                signals.append(Signal(
                    name="NEW_USER_HIGH_VALUE",
                    score=30,
                    detail=f"First-seen user {user_id[:8]}... with high-value transaction.",
                    weight=1.0,
                ))

        # First-seen device
        if device_id and device_id not in self._known_devices:
            if user_id in self._known_users:
                signals.append(Signal(
                    name="NEW_DEVICE",
                    score=20,
                    detail=f"Known user on a new device ({device_id}).",
                    weight=0.8,
                ))

        return signals

    # ------------------------------------------------------------------
    # Detection: Missing Sources
    # ------------------------------------------------------------------

    def _check_missing_sources(self, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict]) -> List[Signal]:
        signals = []
        present = sum(1 for s in [pg, cbs, mobile] if s)

        if present == 1:
            signals.append(Signal(
                name="CRITICAL_DATA_LOSS",
                score=95,
                detail="Transaction exists in only 1 of 3 systems. Severe synchronization failure.",
                weight=2.0,
            ))
        elif not cbs and pg:
            # CBS is the most critical - core banking
            drop_rate = self._source_drops.get("cbs", 0) / max(self._source_totals.get("cbs", 1), 1) * 100
            signals.append(Signal(
                name="MISSING_CBS",
                score=80,
                detail=f"Core Banking System data missing. CBS historical drop rate: {drop_rate:.1f}%.",
                weight=1.8,
            ))
        elif not mobile and pg:
            signals.append(Signal(
                name="MISSING_MOBILE",
                score=50,
                detail="Mobile banking data missing. API gateway sync failure likely.",
                weight=1.0,
            ))
        elif not pg and (cbs or mobile):
            signals.append(Signal(
                name="GHOST_TRANSACTION",
                score=85,
                detail="Transaction exists downstream but NOT in Payment Gateway. Possible injection attack.",
                weight=1.8,
            ))

        return signals

    # ------------------------------------------------------------------
    # Detection: Cross-Source Timing
    # ------------------------------------------------------------------

    def _check_timing(self, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict]) -> List[Signal]:
        signals = []
        sources = {"pg": pg, "cbs": cbs, "mobile": mobile}
        arrival_times = {}
        for name, data in sources.items():
            if data and "timestamp" in data:
                arrival_times[name] = data["timestamp"]

        if len(arrival_times) >= 2:
            times = list(arrival_times.values())
            max_delay = max(times) - min(times)

            # Compare against adaptive baseline
            for name in arrival_times:
                stats = self._propagation_stats[name]
                if stats.count >= 10:
                    z = stats.z_score(arrival_times[name])
                    if z > 3.0:
                        signals.append(Signal(
                            name="ABNORMAL_PROPAGATION",
                            score=30,
                            detail=f"Source '{name}' arrival time deviates from baseline (Z={z:.1f}). Possible replay or routing issue.",
                            weight=0.9,
                        ))
                        break

        return signals

    # ------------------------------------------------------------------
    # Update rolling statistics
    # ------------------------------------------------------------------

    def _update_stats(self, primary: Dict, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict]) -> None:
        amount = primary.get("amount", 0)
        country = primary.get("country", "XX")
        bank = primary.get("bank", "UNKNOWN")
        user_id = primary.get("user_id", "")
        device_id = primary.get("device_id", "")

        # Amount stats
        key = f"{country}:{bank}"
        self._amount_stats[key].update(amount)

        # Source reliability
        for name, data in [("pg", pg), ("cbs", cbs), ("mobile", mobile)]:
            self._source_totals[name] += 1
            if data is None:
                self._source_drops[name] += 1

        # Propagation timing stats
        for name, data in [("pg", pg), ("cbs", cbs), ("mobile", mobile)]:
            if data and "timestamp" in data:
                self._propagation_stats[name].update(data["timestamp"])

        # Track known entities
        if user_id:
            self._known_users.add(user_id)
        if device_id:
            self._known_devices.add(device_id)

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    def _synthesize_analysis(
        self,
        signals: List[Signal],
        pg: Optional[Dict],
        cbs: Optional[Dict],
        mobile: Optional[Dict],
    ) -> str:
        """Generate a human-readable analysis from detected signals."""
        if not signals:
            sources = sum(1 for s in [pg, cbs, mobile] if s)
            return f"All {sources}-way checks passed. No anomalies detected."

        # Sort by weighted score descending
        ranked = sorted(signals, key=lambda s: s.score * s.weight, reverse=True)

        parts = []
        top = ranked[0]

        # Lead with the highest-risk finding
        if top.score >= 80:
            parts.append(f"CRITICAL: {top.detail}")
        elif top.score >= 50:
            parts.append(f"WARNING: {top.detail}")
        else:
            parts.append(top.detail)

        # Add secondary signals (up to 2 more)
        for sig in ranked[1:3]:
            if sig.score >= 15:
                parts.append(sig.detail)

        return " | ".join(parts)

    def _build_result(self, tx_id: str, signals: List[Signal], analysis: str) -> Dict[str, Any]:
        """Build the final result dict compatible with the alert system."""

        if not signals:
            return {
                "ok": True,
                "analysis": analysis,
                "risk_score": 0,
                "risk_level": "LOW",
                "signals": [],
                "recommended_action": "No action required. Transaction verified.",
                "confidence": 1.0,
                "raw": {
                    "risk_level": "LOW",
                    "severity": "low",
                    "confidence": 1.0,
                    "root_cause": "All systems in agreement.",
                    "recommended_action": "No action required.",
                },
                "generated_at": time.time(),
            }

        # Weighted risk score
        total_weight = sum(s.weight for s in signals)
        if total_weight > 0:
            raw_score = sum(s.score * s.weight for s in signals) / total_weight
        else:
            raw_score = 0

        # Boost if multiple independent signals agree
        unique_names = set(s.name for s in signals)
        if len(unique_names) >= 3:
            raw_score = min(100, raw_score * 1.15)
        elif len(unique_names) >= 2:
            raw_score = min(100, raw_score * 1.05)

        risk_score = int(min(100, max(0, raw_score)))

        # Risk level
        if risk_score >= 80:
            risk_level = "CRITICAL"
            severity = "critical"
        elif risk_score >= 60:
            risk_level = "HIGH"
            severity = "high"
        elif risk_score >= 35:
            risk_level = "MEDIUM"
            severity = "medium"
        else:
            risk_level = "LOW"
            severity = "low"

        # Confidence: higher with more data points, lower with fewer signals  
        stat_count = sum(1 for s in signals if "STATISTICAL" in s.name or "Z-score" in s.detail)
        base_confidence = 0.7 + min(0.25, self.total_analyzed / 1000)
        if stat_count > 0:
            base_confidence = min(0.99, base_confidence + 0.1)
        confidence = round(min(0.99, base_confidence), 2)

        # Recommended action
        top_signal = max(signals, key=lambda s: s.score * s.weight)
        action = self._recommend_action(top_signal, risk_level)

        return {
            "ok": True,
            "analysis": analysis,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "signals": [{"name": s.name, "score": round(s.score, 1), "detail": s.detail} for s in signals],
            "recommended_action": action,
            "confidence": confidence,
            "raw": {
                "risk_level": risk_level,
                "severity": severity,
                "confidence": confidence,
                "root_cause": top_signal.detail,
                "recommended_action": action,
            },
            "generated_at": time.time(),
        }

    @staticmethod
    def _recommend_action(top_signal: Signal, risk_level: str) -> str:
        """Generate actionable recommendation based on the top signal."""
        name = top_signal.name

        actions = {
            "EXTREME_AMOUNT_DEVIATION": "Immediately freeze transaction and escalate to fraud team. Trigger full audit trail.",
            "CRITICAL_DATA_LOSS": "Halt processing. Investigate system connectivity. Check message broker health across all 3 sources.",
            "GHOST_TRANSACTION": "Flag for security review. Possible unauthorized injection. Check PG API logs for missing entry.",
            "MISSING_CBS": "Trigger CBS replay. Check Core Banking API health. Verify database write path.",
            "VELOCITY_CRITICAL": "Temporarily block user account. Investigate for automated/bot activity.",
            "STATISTICAL_OUTLIER": "Review transaction against user history. May indicate compromised account.",
            "SIGNIFICANT_AMOUNT_MISMATCH": "Use consensus voting to resolve. Flag for manual review if auto-mitigation fails.",
            "AMOUNT_MISMATCH": "Apply auto-mitigation via majority consensus. Monitor for recurrence.",
            "STATUS_MISMATCH": "Propagate authoritative status from Payment Gateway. Check webhook delivery.",
            "MISSING_MOBILE": "Trigger mobile sync replay. Check API gateway health.",
            "VELOCITY_WARNING": "Monitor user activity. Consider rate limiting if pattern persists.",
            "HIGH_VALUE": "Apply enhanced verification. Log for compliance reporting.",
            "NEW_USER_HIGH_VALUE": "Apply enhanced KYC verification before clearing.",
            "TIMESTAMP_DRIFT": "Investigate clock synchronization across systems.",
            "SEVERE_TIMESTAMP_DRIFT": "Critical sync issue. Check NTP and message broker lag.",
        }

        if name in actions:
            return actions[name]

        if risk_level == "CRITICAL":
            return "Escalate to operations team immediately. Do not auto-resolve."
        if risk_level == "HIGH":
            return "Review manually. Auto-mitigation may be insufficient."
        return "Monitor and apply standard reconciliation procedures."


# ---------------------------------------------------------------------------
# Singleton engine instance
# ---------------------------------------------------------------------------

engine = AnomalyEngine()
