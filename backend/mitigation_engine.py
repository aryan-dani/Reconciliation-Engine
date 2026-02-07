"""
Intelligent Mitigation Engine — Self-Learning Resolution System
================================================================
A Gen-AI inspired adaptive system that:
1. Maintains per-source trust scores that evolve based on outcomes
2. Uses multiple resolution strategies and picks the best one contextually
3. Implements confidence gates for auto-resolution decisions
4. Tracks system health to detect correlated failures
5. Learns from human feedback to improve over time

Author: Reconciliation Engine Team
"""

import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import math


class MitigationStrategy(Enum):
    """Available mitigation strategies."""
    MAJORITY_VOTE = "majority_vote"           # Classic 2-of-3 consensus
    TRUST_WEIGHTED = "trust_weighted"         # Weighted by source reliability
    SOURCE_OF_TRUTH = "source_of_truth"       # Always trust PG (payment gateway)
    TEMPORAL_CORRELATION = "temporal_corr"    # Consider recent source health
    HYBRID = "hybrid"                         # Combination of above


@dataclass
class SourceTrust:
    """Tracks trust score for a data source with decay and learning."""
    name: str
    base_score: float = 0.85
    current_score: float = 0.85
    correct_count: int = 0
    incorrect_count: int = 0
    total_evaluations: int = 0
    last_updated: float = field(default_factory=time.time)
    
    # Exponential moving average parameters
    alpha: float = 0.1  # Learning rate
    
    def record_outcome(self, was_correct: bool):
        """Update trust score based on resolution outcome."""
        self.total_evaluations += 1
        if was_correct:
            self.correct_count += 1
            # Increase trust (bounded)
            delta = self.alpha * (1.0 - self.current_score)
            self.current_score = min(0.99, self.current_score + delta)
        else:
            self.incorrect_count += 1
            # Decrease trust more aggressively (trust is hard to earn, easy to lose)
            delta = self.alpha * 1.5 * self.current_score
            self.current_score = max(0.3, self.current_score - delta)
        self.last_updated = time.time()
    
    def get_accuracy(self) -> float:
        """Calculate historical accuracy rate."""
        if self.total_evaluations == 0:
            return self.base_score
        return self.correct_count / self.total_evaluations
    
    def decay_towards_base(self, decay_rate: float = 0.001):
        """Slowly decay trust back towards base score over time."""
        if self.current_score > self.base_score:
            self.current_score = max(self.base_score, 
                                     self.current_score - decay_rate)
        elif self.current_score < self.base_score:
            self.current_score = min(self.base_score,
                                     self.current_score + decay_rate)


@dataclass 
class SystemHealthState:
    """Tracks health state for a single source system."""
    source: str
    failure_times: deque = field(default_factory=lambda: deque(maxlen=100))
    success_times: deque = field(default_factory=lambda: deque(maxlen=100))
    status: str = "HEALTHY"  # HEALTHY, DEGRADED, DOWN
    degradation_start: Optional[float] = None
    affected_transactions: List[str] = field(default_factory=list)
    
    def record_failure(self, tx_id: str):
        """Record a failure event."""
        now = time.time()
        self.failure_times.append(now)
        self.affected_transactions.append(tx_id)
        if len(self.affected_transactions) > 50:
            self.affected_transactions = self.affected_transactions[-50:]
        self._update_status()
    
    def record_success(self):
        """Record a success event."""
        self.success_times.append(time.time())
        self._update_status()
    
    def _update_status(self):
        """Update health status based on recent failure rate."""
        now = time.time()
        window = 60.0  # 60 second window
        
        recent_failures = sum(1 for t in self.failure_times if now - t < window)
        recent_successes = sum(1 for t in self.success_times if now - t < window)
        total = recent_failures + recent_successes
        
        if total < 5:
            # Not enough data
            if self.status != "HEALTHY":
                self.status = "HEALTHY"
                self.degradation_start = None
            return
        
        failure_rate = recent_failures / total
        
        if failure_rate >= 0.5:
            if self.status != "DOWN":
                self.status = "DOWN"
                self.degradation_start = self.degradation_start or now
        elif failure_rate >= 0.2:
            if self.status == "HEALTHY":
                self.status = "DEGRADED"
                self.degradation_start = now
        else:
            self.status = "HEALTHY"
            self.degradation_start = None
            self.affected_transactions = []
    
    def get_failure_rate(self, window: float = 60.0) -> float:
        """Get failure rate in the specified window."""
        now = time.time()
        recent_failures = sum(1 for t in self.failure_times if now - t < window)
        recent_successes = sum(1 for t in self.success_times if now - t < window)
        total = recent_failures + recent_successes
        return recent_failures / total if total > 0 else 0.0


@dataclass
class StrategyPerformance:
    """Tracks performance metrics for a mitigation strategy."""
    strategy: MitigationStrategy
    attempts: int = 0
    successes: int = 0
    avg_confidence: float = 0.0
    avg_resolution_time: float = 0.0
    _confidence_sum: float = 0.0
    _time_sum: float = 0.0
    
    def record_attempt(self, success: bool, confidence: float, resolution_time: float):
        """Record a strategy attempt and outcome."""
        self.attempts += 1
        if success:
            self.successes += 1
        self._confidence_sum += confidence
        self._time_sum += resolution_time
        self.avg_confidence = self._confidence_sum / self.attempts
        self.avg_resolution_time = self._time_sum / self.attempts
    
    def get_success_rate(self) -> float:
        """Get the success rate for this strategy."""
        return self.successes / self.attempts if self.attempts > 0 else 0.5


@dataclass
class MitigationDecision:
    """The result of a mitigation analysis."""
    should_auto_resolve: bool
    strategy_used: MitigationStrategy
    resolved_values: Dict[str, Any]
    confidence: float
    reasoning: str
    gate_decision: str  # "AUTO_RESOLVED", "HUMAN_REVIEW", "ESCALATED"
    contributing_factors: List[str]
    source_trust_snapshot: Dict[str, float]
    system_health_snapshot: Dict[str, str]
    risk_assessment: str


class MitigationEngine:
    """
    Intelligent Mitigation Engine with adaptive learning.
    
    The engine maintains:
    - Per-source trust scores that adapt based on resolution outcomes
    - System health tracking for detecting correlated failures
    - Strategy performance metrics for choosing optimal approaches
    - Confidence thresholds for gating auto-resolution decisions
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        
        # Source trust tracking
        self._source_trust: Dict[str, SourceTrust] = {
            "pg": SourceTrust("pg", base_score=0.92, current_score=0.92),
            "cbs": SourceTrust("cbs", base_score=0.85, current_score=0.85),
            "mobile": SourceTrust("mobile", base_score=0.80, current_score=0.80),
        }
        
        # System health tracking
        self._system_health: Dict[str, SystemHealthState] = {
            "pg": SystemHealthState("pg"),
            "cbs": SystemHealthState("cbs"),
            "mobile": SystemHealthState("mobile"),
        }
        
        # Strategy performance tracking
        self._strategy_performance: Dict[MitigationStrategy, StrategyPerformance] = {
            strategy: StrategyPerformance(strategy) 
            for strategy in MitigationStrategy
        }
        
        # Confidence thresholds
        self.auto_resolve_confidence_threshold = 0.85
        self.auto_resolve_risk_threshold = 60
        self.escalation_confidence_threshold = 0.70
        
        # Learning metrics
        self._total_mitigations = 0
        self._auto_resolved_count = 0
        self._human_reviewed_count = 0
        self._escalated_count = 0
        self._correct_auto_resolves = 0
        self._feedback_history: deque = deque(maxlen=500)
        
        # Root cause tracking
        self._active_incidents: Dict[str, Dict] = {}
    
    def analyze_and_decide(
        self,
        tx_id: str,
        pg_data: Optional[Dict],
        cbs_data: Optional[Dict],
        mobile_data: Optional[Dict],
        issue_type: str,
        anomaly_confidence: float,
        risk_score: int
    ) -> MitigationDecision:
        """
        Analyze a mismatch and decide on mitigation strategy.
        
        Returns a MitigationDecision with:
        - Whether to auto-resolve
        - Which strategy to use
        - The resolved values
        - Confidence level
        - Reasoning
        """
        with self._lock:
            self._total_mitigations += 1
            
            # Get current state snapshots
            trust_snapshot = {k: v.current_score for k, v in self._source_trust.items()}
            health_snapshot = {k: v.status for k, v in self._system_health.items()}
            
            # Determine best strategy based on context
            strategy, strategy_reasoning = self._select_strategy(
                issue_type, health_snapshot, trust_snapshot
            )
            
            # Execute the strategy
            resolved_values, resolution_confidence, resolution_reasoning = self._execute_strategy(
                strategy, pg_data, cbs_data, mobile_data, issue_type, trust_snapshot
            )
            
            # Combine confidences
            combined_confidence = (anomaly_confidence * 0.4 + resolution_confidence * 0.6)
            
            # Apply confidence gates
            gate_decision, gate_reasoning = self._apply_confidence_gates(
                combined_confidence, risk_score, issue_type, health_snapshot
            )
            
            # Build contributing factors
            factors = self._build_contributing_factors(
                trust_snapshot, health_snapshot, strategy, resolution_confidence
            )
            
            # Assess risk
            risk_assessment = self._assess_risk(risk_score, health_snapshot, issue_type)
            
            # Build full reasoning
            full_reasoning = (
                f"Strategy: {strategy.value} - {strategy_reasoning}. "
                f"Resolution: {resolution_reasoning}. "
                f"Gate: {gate_reasoning}."
            )
            
            decision = MitigationDecision(
                should_auto_resolve=(gate_decision == "AUTO_RESOLVED"),
                strategy_used=strategy,
                resolved_values=resolved_values,
                confidence=combined_confidence,
                reasoning=full_reasoning,
                gate_decision=gate_decision,
                contributing_factors=factors,
                source_trust_snapshot=trust_snapshot,
                system_health_snapshot=health_snapshot,
                risk_assessment=risk_assessment
            )
            
            # Update counters
            if gate_decision == "AUTO_RESOLVED":
                self._auto_resolved_count += 1
            elif gate_decision == "HUMAN_REVIEW":
                self._human_reviewed_count += 1
            else:
                self._escalated_count += 1
            
            return decision
    
    def _select_strategy(
        self,
        issue_type: str,
        health: Dict[str, str],
        trust: Dict[str, float]
    ) -> Tuple[MitigationStrategy, str]:
        """Select the best strategy based on current context."""
        
        # If a source is DOWN, use temporal correlation
        down_sources = [s for s, status in health.items() if status == "DOWN"]
        if down_sources:
            return (
                MitigationStrategy.TEMPORAL_CORRELATION,
                f"Source(s) {down_sources} detected as DOWN — using temporal correlation"
            )
        
        # If a source is DEGRADED, favor trust-weighted
        degraded_sources = [s for s, status in health.items() if status == "DEGRADED"]
        if degraded_sources:
            return (
                MitigationStrategy.TRUST_WEIGHTED,
                f"Source(s) {degraded_sources} degraded — using trust-weighted resolution"
            )
        
        # For status mismatches, PG is source of truth
        if issue_type == "STATUS_MISMATCH":
            return (
                MitigationStrategy.SOURCE_OF_TRUTH,
                "Status mismatch — PG is authoritative source of truth"
            )
        
        # Check if trust scores have diverged significantly
        trust_variance = max(trust.values()) - min(trust.values())
        if trust_variance > 0.15:
            return (
                MitigationStrategy.TRUST_WEIGHTED,
                f"Trust scores diverged ({trust_variance:.2f}) — using trust-weighted"
            )
        
        # Check strategy performance history
        best_strategy = self._get_best_performing_strategy()
        if best_strategy and self._strategy_performance[best_strategy].attempts >= 20:
            perf = self._strategy_performance[best_strategy]
            if perf.get_success_rate() > 0.85:
                return (
                    best_strategy,
                    f"Using historically best strategy (success rate: {perf.get_success_rate():.1%})"
                )
        
        # Default to hybrid
        return (
            MitigationStrategy.HYBRID,
            "Using hybrid approach combining multiple signals"
        )
    
    def _execute_strategy(
        self,
        strategy: MitigationStrategy,
        pg: Optional[Dict],
        cbs: Optional[Dict],
        mobile: Optional[Dict],
        issue_type: str,
        trust: Dict[str, float]
    ) -> Tuple[Dict[str, Any], float, str]:
        """Execute the selected strategy and return resolved values."""
        
        if strategy == MitigationStrategy.MAJORITY_VOTE:
            return self._majority_vote(pg, cbs, mobile, issue_type)
        
        elif strategy == MitigationStrategy.TRUST_WEIGHTED:
            return self._trust_weighted(pg, cbs, mobile, issue_type, trust)
        
        elif strategy == MitigationStrategy.SOURCE_OF_TRUTH:
            return self._source_of_truth(pg, cbs, mobile, issue_type)
        
        elif strategy == MitigationStrategy.TEMPORAL_CORRELATION:
            return self._temporal_correlation(pg, cbs, mobile, issue_type)
        
        else:  # HYBRID
            return self._hybrid(pg, cbs, mobile, issue_type, trust)
    
    def _majority_vote(
        self, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict], issue_type: str
    ) -> Tuple[Dict[str, Any], float, str]:
        """Classic 2-of-3 majority voting."""
        if issue_type in ["AMOUNT_MISMATCH", "FRAUD"]:
            amounts = []
            if pg: amounts.append(("pg", pg.get("amount", 0)))
            if cbs: amounts.append(("cbs", cbs.get("amount", 0)))
            if mobile: amounts.append(("mobile", mobile.get("amount", 0)))
            
            # Count votes
            amount_votes = defaultdict(list)
            for source, amt in amounts:
                amount_votes[amt].append(source)
            
            # Find majority
            consensus_amount, voters = max(amount_votes.items(), key=lambda x: len(x[1]))
            confidence = len(voters) / len(amounts) if amounts else 0.5
            
            return (
                {"amount": consensus_amount, "sources_agreed": voters},
                confidence,
                f"Majority vote: {len(voters)}/{len(amounts)} sources agreed on {consensus_amount}"
            )
        
        elif issue_type == "STATUS_MISMATCH":
            statuses = []
            if pg: statuses.append(("pg", pg.get("status", "UNKNOWN")))
            if cbs: statuses.append(("cbs", cbs.get("status", "UNKNOWN")))
            if mobile: statuses.append(("mobile", mobile.get("status", "UNKNOWN")))
            
            status_votes = defaultdict(list)
            for source, status in statuses:
                status_votes[status].append(source)
            
            consensus_status, voters = max(status_votes.items(), key=lambda x: len(x[1]))
            confidence = len(voters) / len(statuses) if statuses else 0.5
            
            return (
                {"status": consensus_status, "sources_agreed": voters},
                confidence,
                f"Majority vote: {len(voters)}/{len(statuses)} sources agreed on {consensus_status}"
            )
        
        return ({}, 0.5, "No applicable majority vote resolution")
    
    def _trust_weighted(
        self, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict],
        issue_type: str, trust: Dict[str, float]
    ) -> Tuple[Dict[str, Any], float, str]:
        """Trust-weighted resolution using source reliability scores."""
        if issue_type in ["AMOUNT_MISMATCH", "FRAUD"]:
            weighted_sum = 0.0
            weight_total = 0.0
            contributions = []
            
            if pg:
                w = trust["pg"]
                weighted_sum += pg.get("amount", 0) * w
                weight_total += w
                contributions.append(f"PG({trust['pg']:.2f})")
            if cbs:
                w = trust["cbs"]
                weighted_sum += cbs.get("amount", 0) * w
                weight_total += w
                contributions.append(f"CBS({trust['cbs']:.2f})")
            if mobile:
                w = trust["mobile"]
                weighted_sum += mobile.get("amount", 0) * w
                weight_total += w
                contributions.append(f"Mobile({trust['mobile']:.2f})")
            
            if weight_total > 0:
                weighted_amount = weighted_sum / weight_total
                # Round to 2 decimal places (currency)
                resolved_amount = round(weighted_amount, 2)
                
                # Confidence is proportional to trust concentration
                max_trust = max(trust.values())
                confidence = 0.6 + (max_trust - 0.5) * 0.6  # Scale 0.5-1.0 -> 0.6-0.9
                
                return (
                    {"amount": resolved_amount, "weighted": True},
                    min(0.95, confidence),
                    f"Trust-weighted average: {' + '.join(contributions)} = {resolved_amount}"
                )
        
        # Fallback to source of truth for status
        return self._source_of_truth(pg, cbs, mobile, issue_type)
    
    def _source_of_truth(
        self, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict], issue_type: str
    ) -> Tuple[Dict[str, Any], float, str]:
        """Use PG as the authoritative source."""
        if pg:
            if issue_type in ["AMOUNT_MISMATCH", "FRAUD"]:
                return (
                    {"amount": pg.get("amount", 0), "source": "pg"},
                    0.90,  # High confidence in PG
                    "PG (Payment Gateway) used as source of truth"
                )
            elif issue_type == "STATUS_MISMATCH":
                return (
                    {"status": pg.get("status", "SUCCESS"), "source": "pg"},
                    0.92,
                    "PG status is authoritative"
                )
        
        # No PG available, fall back to CBS
        if cbs:
            return (
                {"amount": cbs.get("amount", 0), "status": cbs.get("status"), "source": "cbs"},
                0.75,
                "CBS used as fallback source (PG unavailable)"
            )
        
        if mobile:
            return (
                {"amount": mobile.get("amount", 0), "status": mobile.get("status"), "source": "mobile"},
                0.60,
                "Mobile used as last resort source"
            )
        
        return ({}, 0.3, "No source available")
    
    def _temporal_correlation(
        self, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict], issue_type: str
    ) -> Tuple[Dict[str, Any], float, str]:
        """Resolution based on recent system health."""
        # Check which sources are healthy
        healthy_sources = []
        degraded_sources = []
        
        for source, health in self._system_health.items():
            if health.status == "HEALTHY":
                healthy_sources.append(source)
            else:
                degraded_sources.append(source)
        
        # Trust only healthy sources
        healthy_data = {}
        if "pg" in healthy_sources and pg:
            healthy_data["pg"] = pg
        if "cbs" in healthy_sources and cbs:
            healthy_data["cbs"] = cbs
        if "mobile" in healthy_sources and mobile:
            healthy_data["mobile"] = mobile
        
        if len(healthy_data) >= 2:
            # Have enough healthy sources for majority vote
            amounts = [(s, d.get("amount", 0)) for s, d in healthy_data.items()]
            amount_votes = defaultdict(list)
            for source, amt in amounts:
                amount_votes[amt].append(source)
            
            consensus, voters = max(amount_votes.items(), key=lambda x: len(x[1]))
            
            return (
                {"amount": consensus, "trusted_sources": list(healthy_data.keys())},
                0.85,
                f"Used {len(healthy_data)} healthy sources, excluded degraded: {degraded_sources}"
            )
        
        elif len(healthy_data) == 1:
            source, data = list(healthy_data.items())[0]
            return (
                {"amount": data.get("amount", 0), "single_healthy_source": source},
                0.70,
                f"Only {source} is healthy — using as single source of truth"
            )
        
        # All sources degraded — fall back to PG
        return self._source_of_truth(pg, cbs, mobile, issue_type)
    
    def _hybrid(
        self, pg: Optional[Dict], cbs: Optional[Dict], mobile: Optional[Dict],
        issue_type: str, trust: Dict[str, float]
    ) -> Tuple[Dict[str, Any], float, str]:
        """Hybrid approach combining multiple strategies."""
        # Get results from multiple strategies
        majority_result, majority_conf, _ = self._majority_vote(pg, cbs, mobile, issue_type)
        trust_result, trust_conf, _ = self._trust_weighted(pg, cbs, mobile, issue_type, trust)
        sot_result, sot_conf, _ = self._source_of_truth(pg, cbs, mobile, issue_type)
        
        # If all agree, high confidence
        if issue_type in ["AMOUNT_MISMATCH", "FRAUD"]:
            majority_amt = majority_result.get("amount", 0)
            trust_amt = trust_result.get("amount", 0)
            sot_amt = sot_result.get("amount", 0)
            
            # Check agreement (within 1% tolerance for weighted)
            if abs(majority_amt - sot_amt) < 0.01 and abs(trust_amt - sot_amt) / max(sot_amt, 1) < 0.01:
                return (
                    {"amount": sot_amt, "strategy": "unanimous"},
                    0.95,
                    "All strategies agree — unanimous resolution"
                )
            
            # Weight by confidence
            total_weight = majority_conf + trust_conf + sot_conf
            weighted_amount = (
                majority_amt * majority_conf +
                trust_amt * trust_conf +
                sot_amt * sot_conf
            ) / total_weight
            
            avg_confidence = total_weight / 3
            
            return (
                {"amount": round(weighted_amount, 2), "strategy": "hybrid_weighted"},
                avg_confidence,
                "Hybrid: weighted combination of majority, trust, and source-of-truth"
            )
        
        # For status, prefer PG
        return sot_result, sot_conf, "Hybrid: using source-of-truth for status"
    
    def _apply_confidence_gates(
        self,
        confidence: float,
        risk_score: int,
        issue_type: str,
        health: Dict[str, str]
    ) -> Tuple[str, str]:
        """Apply confidence gates to determine resolution path."""
        
        # Never auto-resolve potential fraud without human review
        if issue_type == "FRAUD" or risk_score >= 90:
            return ("ESCALATED", "High fraud risk requires human review")
        
        # If systems are down, be more cautious
        if any(s == "DOWN" for s in health.values()):
            if confidence >= 0.90 and risk_score < 50:
                return ("AUTO_RESOLVED", "High confidence despite system outage")
            return ("HUMAN_REVIEW", "System outage detected — requesting human verification")
        
        # Standard gates
        if confidence >= self.auto_resolve_confidence_threshold:
            if risk_score < self.auto_resolve_risk_threshold:
                return ("AUTO_RESOLVED", f"Confidence {confidence:.1%} >= {self.auto_resolve_confidence_threshold:.0%}, risk {risk_score} < {self.auto_resolve_risk_threshold}")
            else:
                return ("HUMAN_REVIEW", f"High risk score ({risk_score}) despite good confidence")
        
        elif confidence >= self.escalation_confidence_threshold:
            return ("HUMAN_REVIEW", f"Moderate confidence {confidence:.1%} — recommend human review")
        
        else:
            return ("ESCALATED", f"Low confidence {confidence:.1%} — escalating to senior review")
    
    def _build_contributing_factors(
        self,
        trust: Dict[str, float],
        health: Dict[str, str],
        strategy: MitigationStrategy,
        confidence: float
    ) -> List[str]:
        """Build list of factors that influenced the decision."""
        factors = []
        
        # Trust factors
        low_trust = [s for s, t in trust.items() if t < 0.7]
        if low_trust:
            factors.append(f"Low trust in: {', '.join(low_trust)}")
        
        high_trust = [s for s, t in trust.items() if t > 0.9]
        if high_trust:
            factors.append(f"High trust in: {', '.join(high_trust)}")
        
        # Health factors
        unhealthy = [s for s, h in health.items() if h != "HEALTHY"]
        if unhealthy:
            factors.append(f"Degraded/Down systems: {', '.join(unhealthy)}")
        
        # Strategy factor
        factors.append(f"Selected strategy: {strategy.value}")
        
        # Confidence factor
        if confidence >= 0.9:
            factors.append("Very high resolution confidence")
        elif confidence >= 0.8:
            factors.append("Good resolution confidence")
        elif confidence >= 0.7:
            factors.append("Moderate resolution confidence")
        else:
            factors.append("Low resolution confidence — caution advised")
        
        return factors
    
    def _assess_risk(
        self,
        risk_score: int,
        health: Dict[str, str],
        issue_type: str
    ) -> str:
        """Generate human-readable risk assessment."""
        if risk_score >= 90:
            return "CRITICAL: Potential fraud detected. Manual investigation required."
        elif risk_score >= 70:
            return "HIGH: Significant anomaly. Recommend careful review before resolution."
        elif risk_score >= 50:
            return "MEDIUM: Notable discrepancy. Standard review process applies."
        elif risk_score >= 30:
            return "LOW-MEDIUM: Minor inconsistency. Likely safe to auto-resolve."
        else:
            return "LOW: Routine discrepancy. Safe for automatic resolution."
    
    def _get_best_performing_strategy(self) -> Optional[MitigationStrategy]:
        """Get the strategy with the best historical performance."""
        best = None
        best_score = 0.0
        
        for strategy, perf in self._strategy_performance.items():
            if perf.attempts >= 10:  # Need minimum samples
                score = perf.get_success_rate() * perf.avg_confidence
                if score > best_score:
                    best_score = score
                    best = strategy
        
        return best
    
    # === Public APIs for feedback and health tracking ===
    
    def record_source_failure(self, source: str, tx_id: str):
        """Record a failure for a source (missing data, timeout, etc.)."""
        with self._lock:
            if source in self._system_health:
                self._system_health[source].record_failure(tx_id)
                self._source_trust[source].decay_towards_base(0.005)  # Slight trust decay
    
    def record_source_success(self, source: str):
        """Record a successful data receipt from a source."""
        with self._lock:
            if source in self._system_health:
                self._system_health[source].record_success()
    
    def record_resolution_feedback(
        self,
        tx_id: str,
        engine_recommendation: str,
        human_choice: str,
        strategy_used: MitigationStrategy
    ):
        """
        Record feedback when a human resolves a transaction.
        This teaches the engine which sources to trust more.
        """
        with self._lock:
            was_correct = (engine_recommendation == human_choice)
            
            # Update strategy performance
            self._strategy_performance[strategy_used].record_attempt(
                success=was_correct,
                confidence=0.0,  # Would need to store this
                resolution_time=0.0
            )
            
            # Update source trust based on which source human chose
            if human_choice in ["accept_pg", "pg"]:
                self._source_trust["pg"].record_outcome(True)
                self._source_trust["cbs"].record_outcome(False)
                self._source_trust["mobile"].record_outcome(False)
            elif human_choice in ["accept_cbs", "cbs"]:
                self._source_trust["cbs"].record_outcome(True)
                self._source_trust["pg"].record_outcome(False)
            elif human_choice in ["accept_mobile", "mobile"]:
                self._source_trust["mobile"].record_outcome(True)
                self._source_trust["pg"].record_outcome(False)
            
            # Track in history
            self._feedback_history.append({
                "tx_id": tx_id,
                "engine_said": engine_recommendation,
                "human_chose": human_choice,
                "was_correct": was_correct,
                "timestamp": time.time()
            })
            
            # Update correct count if engine was right
            if was_correct:
                self._correct_auto_resolves += 1
    
    def get_system_health_report(self) -> Dict[str, Any]:
        """Get current system health status."""
        with self._lock:
            return {
                source: {
                    "status": health.status,
                    "failure_rate": health.get_failure_rate(),
                    "degradation_start": health.degradation_start,
                    "affected_count": len(health.affected_transactions)
                }
                for source, health in self._system_health.items()
            }
    
    def get_active_incidents(self) -> List[Dict]:
        """Get list of active system incidents (for root cause display)."""
        with self._lock:
            incidents = []
            for source, health in self._system_health.items():
                if health.status != "HEALTHY":
                    duration = time.time() - health.degradation_start if health.degradation_start else 0
                    incidents.append({
                        "source": source,
                        "status": health.status,
                        "duration_seconds": duration,
                        "affected_transactions": len(health.affected_transactions),
                        "failure_rate": health.get_failure_rate()
                    })
            return incidents
    
    def get_learning_metrics(self) -> Dict[str, Any]:
        """Get metrics about the engine's learning progress."""
        with self._lock:
            total_feedback = len(self._feedback_history)
            correct_feedback = sum(1 for f in self._feedback_history if f["was_correct"])
            
            return {
                "total_mitigations": self._total_mitigations,
                "auto_resolved": self._auto_resolved_count,
                "human_reviewed": self._human_reviewed_count,
                "escalated": self._escalated_count,
                "auto_resolve_rate": self._auto_resolved_count / max(1, self._total_mitigations),
                "feedback_count": total_feedback,
                "feedback_accuracy": correct_feedback / max(1, total_feedback),
                "source_trust": {k: v.current_score for k, v in self._source_trust.items()},
                "source_accuracy": {k: v.get_accuracy() for k, v in self._source_trust.items()},
                "strategy_performance": {
                    s.value: {
                        "attempts": p.attempts,
                        "success_rate": p.get_success_rate(),
                        "avg_confidence": p.avg_confidence
                    }
                    for s, p in self._strategy_performance.items()
                    if p.attempts > 0
                },
                "active_incidents": self.get_active_incidents()
            }
    
    def get_trust_scores(self) -> Dict[str, float]:
        """Get current trust scores for all sources."""
        with self._lock:
            return {k: v.current_score for k, v in self._source_trust.items()}


# Singleton instance
mitigation_engine = MitigationEngine()
