"""
Fraud Ring Detection Engine
============================
Real-time detection of coordinated fraud attempts and suspicious transaction patterns.

Hackathon Feature: Detects "fraud rings" - groups of accounts that exhibit suspicious
patterns like circular transactions, coordinated timing, or amount manipulation.

Key Features:
- Transaction graph construction
- Cycle detection (money laundering patterns)
- Velocity anomalies per account
- Cross-account correlation
- Risk scoring for account clusters
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple
from datetime import datetime, timedelta
import time
import threading
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class AccountNode:
    """Represents an account in the transaction graph."""
    account_id: str
    total_sent: float = 0.0
    total_received: float = 0.0
    transaction_count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    connected_accounts: Set[str] = field(default_factory=set)
    risk_score: float = 0.0
    flags: List[str] = field(default_factory=list)
    
    def velocity(self, window_seconds: float = 300) -> float:
        """Calculate transactions per minute in recent window."""
        time_span = max(1, self.last_seen - self.first_seen)
        if time_span < window_seconds:
            return self.transaction_count / (time_span / 60)
        return self.transaction_count / (window_seconds / 60)


@dataclass  
class TransactionEdge:
    """Represents a transaction between two accounts."""
    from_account: str
    to_account: str
    amount: float
    timestamp: float
    tx_id: str
    currency: str = "INR"
    flags: List[str] = field(default_factory=list)


@dataclass
class FraudRing:
    """Represents a detected fraud ring."""
    ring_id: str
    accounts: List[str]
    total_volume: float
    transaction_count: int
    detection_time: float
    ring_type: str  # 'cycle', 'burst', 'coordinated', 'layering'
    risk_score: float
    evidence: List[str]
    is_active: bool = True


class FraudRingDetector:
    """
    Real-time fraud ring detection engine.
    
    Detection Methods:
    1. Cycle Detection - Money going in circles (A -> B -> C -> A)
    2. Burst Detection - Sudden spike in activity from related accounts
    3. Coordinated Timing - Multiple accounts transacting at same time
    4. Layering Detection - Complex chains to obscure money flow
    """
    
    def __init__(self, cycle_detection_depth: int = 5, 
                 velocity_threshold: float = 10.0,
                 correlation_window_seconds: float = 60):
        self.accounts: Dict[str, AccountNode] = {}
        self.edges: List[TransactionEdge] = []
        self.adjacency: Dict[str, Dict[str, List[TransactionEdge]]] = defaultdict(lambda: defaultdict(list))
        self.reverse_adjacency: Dict[str, Dict[str, List[TransactionEdge]]] = defaultdict(lambda: defaultdict(list))
        
        self.detected_rings: List[FraudRing] = []
        self.active_rings: Dict[str, FraudRing] = {}
        
        self.cycle_detection_depth = cycle_detection_depth
        self.velocity_threshold = velocity_threshold
        self.correlation_window = correlation_window_seconds
        
        self.lock = threading.RLock()
        self._ring_counter = 0
        
        # Recent transactions for correlation detection
        self.recent_transactions: List[TransactionEdge] = []
        self.max_recent = 1000
        
        # Suspicious patterns
        self.suspicious_amounts = [999, 9999, 99999, 10000, 50000, 100000]  # Round numbers
        self.suspicious_velocity_accounts: Set[str] = set()
        
    def _generate_ring_id(self) -> str:
        self._ring_counter += 1
        return f"RING-{int(time.time())}-{self._ring_counter:04d}"
    
    def add_transaction(self, tx_id: str, from_account: str, to_account: Optional[str],
                       amount: float, timestamp: float = None, currency: str = "INR") -> List[FraudRing]:
        """
        Add a transaction to the graph and check for fraud patterns.
        Returns list of newly detected fraud rings.
        """
        if timestamp is None:
            timestamp = time.time()
            
        # Skip if no destination (e.g., withdrawals)
        if not to_account or from_account == to_account:
            return []
            
        new_rings = []
        
        with self.lock:
            # Create or update account nodes
            if from_account not in self.accounts:
                self.accounts[from_account] = AccountNode(account_id=from_account)
            if to_account not in self.accounts:
                self.accounts[to_account] = AccountNode(account_id=to_account)
            
            from_node = self.accounts[from_account]
            to_node = self.accounts[to_account]
            
            # Update account stats
            from_node.total_sent += amount
            from_node.transaction_count += 1
            from_node.last_seen = timestamp
            from_node.connected_accounts.add(to_account)
            
            to_node.total_received += amount
            to_node.transaction_count += 1
            to_node.last_seen = timestamp
            to_node.connected_accounts.add(from_account)
            
            # Create edge
            edge = TransactionEdge(
                from_account=from_account,
                to_account=to_account,
                amount=amount,
                timestamp=timestamp,
                tx_id=tx_id,
                currency=currency
            )
            
            # Check for suspicious patterns
            if self._is_suspicious_amount(amount):
                edge.flags.append("SUSPICIOUS_AMOUNT")
                from_node.flags.append(f"SUSPICIOUS_AMOUNT:{tx_id}")
            
            self.edges.append(edge)
            self.adjacency[from_account][to_account].append(edge)
            self.reverse_adjacency[to_account][from_account].append(edge)
            
            # Add to recent transactions
            self.recent_transactions.append(edge)
            if len(self.recent_transactions) > self.max_recent:
                self.recent_transactions = self.recent_transactions[-self.max_recent:]
            
            # Run fraud detection checks
            
            # 1. Cycle Detection
            cycles = self._detect_cycles(from_account)
            for cycle in cycles:
                ring = self._create_ring_from_cycle(cycle, "cycle")
                if ring:
                    new_rings.append(ring)
            
            # 2. Velocity Anomaly
            if from_node.velocity() > self.velocity_threshold:
                if from_account not in self.suspicious_velocity_accounts:
                    self.suspicious_velocity_accounts.add(from_account)
                    from_node.flags.append("HIGH_VELOCITY")
                    from_node.risk_score += 30
                    
                    # Check if connected accounts also have high velocity
                    burst_accounts = self._detect_burst_pattern(from_account)
                    if len(burst_accounts) >= 3:
                        ring = self._create_ring_from_accounts(burst_accounts, "burst")
                        if ring:
                            new_rings.append(ring)
            
            # 3. Coordinated Timing
            coordinated = self._detect_coordinated_timing(timestamp)
            if len(coordinated) >= 3:
                ring = self._create_ring_from_accounts(
                    [e.from_account for e in coordinated], 
                    "coordinated"
                )
                if ring:
                    new_rings.append(ring)
            
            # 4. Layering Detection (complex chains)
            layering = self._detect_layering(from_account)
            if layering:
                ring = self._create_ring_from_accounts(layering, "layering")
                if ring:
                    new_rings.append(ring)
            
            # Update risk scores based on connections
            self._update_risk_propagation(from_account, to_account)
            
        return new_rings
    
    def _is_suspicious_amount(self, amount: float) -> bool:
        """Check if amount matches suspicious patterns."""
        # Check for exact round numbers
        if amount in self.suspicious_amounts:
            return True
        # Check for amounts just under round numbers (structuring)
        for threshold in [10000, 50000, 100000, 500000]:
            if threshold * 0.95 <= amount < threshold:
                return True
        return False
    
    def _detect_cycles(self, start_account: str) -> List[List[str]]:
        """Detect cycles starting from an account using DFS."""
        cycles = []
        visited = set()
        path = []
        
        def dfs(account: str, depth: int):
            if depth > self.cycle_detection_depth:
                return
            if account in path:
                # Found a cycle
                cycle_start = path.index(account)
                cycle = path[cycle_start:] + [account]
                if len(cycle) >= 3:  # Minimum 3 accounts for a meaningful cycle
                    cycles.append(cycle)
                return
            if account in visited:
                return
            
            visited.add(account)
            path.append(account)
            
            for neighbor in self.adjacency[account]:
                dfs(neighbor, depth + 1)
            
            path.pop()
        
        dfs(start_account, 0)
        return cycles
    
    def _detect_burst_pattern(self, account: str) -> List[str]:
        """Detect accounts with coordinated high velocity."""
        burst_accounts = [account]
        
        node = self.accounts.get(account)
        if not node:
            return burst_accounts
        
        for connected in node.connected_accounts:
            connected_node = self.accounts.get(connected)
            if connected_node and connected_node.velocity() > self.velocity_threshold * 0.5:
                burst_accounts.append(connected)
        
        return burst_accounts
    
    def _detect_coordinated_timing(self, current_timestamp: float) -> List[TransactionEdge]:
        """Find transactions that happened very close together."""
        coordinated = []
        
        for edge in reversed(self.recent_transactions):
            if current_timestamp - edge.timestamp <= self.correlation_window:
                coordinated.append(edge)
            else:
                break
        
        return coordinated
    
    def _detect_layering(self, account: str, depth: int = 0, visited: Set[str] = None) -> Optional[List[str]]:
        """Detect layering patterns (A -> B -> C -> D with similar amounts)."""
        if visited is None:
            visited = set()
        
        if depth > 4 or account in visited:
            return None
        
        visited.add(account)
        
        # Look for chains where money flows through with minimal changes
        for neighbor in self.adjacency[account]:
            edges_to_neighbor = self.adjacency[account][neighbor]
            if not edges_to_neighbor:
                continue
            
            # Check if neighbor forwards similar amount
            for out_neighbor in self.adjacency[neighbor]:
                edges_from_neighbor = self.adjacency[neighbor][out_neighbor]
                if edges_from_neighbor:
                    # Compare amounts - if within 10%, could be layering
                    for e1 in edges_to_neighbor[-5:]:  # Recent edges
                        for e2 in edges_from_neighbor[-5:]:
                            if abs(e1.amount - e2.amount) / max(e1.amount, 1) < 0.1:
                                # Potential layering detected
                                chain = self._detect_layering(out_neighbor, depth + 1, visited)
                                if chain:
                                    return [account, neighbor] + chain
                                elif depth >= 2:
                                    return [account, neighbor, out_neighbor]
        
        return None
    
    def _create_ring_from_cycle(self, cycle: List[str], ring_type: str) -> Optional[FraudRing]:
        """Create a fraud ring from a detected cycle."""
        if len(cycle) < 3:
            return None
        
        # Check if we've already detected this ring
        cycle_set = frozenset(cycle[:-1])  # Exclude last element (duplicate of first)
        for existing in self.detected_rings[-50:]:  # Check recent rings
            if frozenset(existing.accounts) == cycle_set:
                return None
        
        # Calculate ring statistics
        total_volume = 0
        tx_count = 0
        accounts = list(cycle_set)
        
        for i in range(len(accounts)):
            for neighbor in self.adjacency[accounts[i]]:
                if neighbor in cycle_set:
                    edges = self.adjacency[accounts[i]][neighbor]
                    total_volume += sum(e.amount for e in edges)
                    tx_count += len(edges)
        
        ring = FraudRing(
            ring_id=self._generate_ring_id(),
            accounts=accounts,
            total_volume=total_volume,
            transaction_count=tx_count,
            detection_time=time.time(),
            ring_type=ring_type,
            risk_score=self._calculate_ring_risk(accounts),
            evidence=[
                f"Cycle detected: {' -> '.join(cycle)}",
                f"Total volume: {total_volume:.2f}",
                f"Transaction count: {tx_count}"
            ]
        )
        
        self.detected_rings.append(ring)
        self.active_rings[ring.ring_id] = ring
        
        logger.warning(f"🚨 FRAUD RING DETECTED: {ring.ring_id} - Type: {ring_type} - Accounts: {accounts}")
        
        return ring
    
    def _create_ring_from_accounts(self, accounts: List[str], ring_type: str) -> Optional[FraudRing]:
        """Create a fraud ring from a list of suspicious accounts."""
        if len(accounts) < 2:
            return None
        
        # Deduplicate
        accounts = list(set(accounts))
        
        # Check if we've already detected this ring recently
        accounts_set = frozenset(accounts)
        for existing in self.detected_rings[-20:]:
            if frozenset(existing.accounts) == accounts_set and existing.ring_type == ring_type:
                return None
        
        # Calculate statistics
        total_volume = sum(self.accounts[a].total_sent + self.accounts[a].total_received 
                          for a in accounts if a in self.accounts)
        tx_count = sum(self.accounts[a].transaction_count 
                       for a in accounts if a in self.accounts)
        
        evidence = [
            f"Ring type: {ring_type}",
            f"Accounts involved: {len(accounts)}",
            f"Combined volume: {total_volume:.2f}"
        ]
        
        if ring_type == "burst":
            evidence.append(f"High velocity detected across multiple connected accounts")
        elif ring_type == "coordinated":
            evidence.append(f"Transactions occurred within {self.correlation_window}s window")
        elif ring_type == "layering":
            evidence.append(f"Money flow chain with similar amounts detected")
        
        ring = FraudRing(
            ring_id=self._generate_ring_id(),
            accounts=accounts,
            total_volume=total_volume,
            transaction_count=tx_count,
            detection_time=time.time(),
            ring_type=ring_type,
            risk_score=self._calculate_ring_risk(accounts),
            evidence=evidence
        )
        
        self.detected_rings.append(ring)
        self.active_rings[ring.ring_id] = ring
        
        logger.warning(f"🚨 FRAUD RING DETECTED: {ring.ring_id} - Type: {ring_type} - Accounts: {accounts}")
        
        return ring
    
    def _calculate_ring_risk(self, accounts: List[str]) -> float:
        """Calculate risk score for a ring."""
        base_risk = 50.0
        
        # Add risk based on individual account risk scores
        for account in accounts:
            if account in self.accounts:
                base_risk += self.accounts[account].risk_score * 0.1
        
        # Higher risk for more accounts
        base_risk += len(accounts) * 5
        
        # Cap at 100
        return min(100.0, base_risk)
    
    def _update_risk_propagation(self, from_account: str, to_account: str):
        """Propagate risk scores through the network."""
        from_node = self.accounts.get(from_account)
        to_node = self.accounts.get(to_account)
        
        if not from_node or not to_node:
            return
        
        # If sender has high risk, increase receiver's risk
        if from_node.risk_score > 50:
            to_node.risk_score = min(100, to_node.risk_score + from_node.risk_score * 0.1)
        
        # If connected to many flagged accounts, increase risk
        flagged_connections = sum(1 for acc in from_node.connected_accounts 
                                  if acc in self.accounts and len(self.accounts[acc].flags) > 0)
        if flagged_connections >= 3:
            from_node.risk_score = min(100, from_node.risk_score + 10)
    
    def get_ring_status(self) -> Dict:
        """Get current fraud ring detection status."""
        with self.lock:
            return {
                "total_accounts": len(self.accounts),
                "total_edges": len(self.edges),
                "detected_rings": len(self.detected_rings),
                "active_rings": len(self.active_rings),
                "high_risk_accounts": len([a for a in self.accounts.values() if a.risk_score > 70]),
                "suspicious_velocity_accounts": len(self.suspicious_velocity_accounts),
                "recent_rings": [
                    {
                        "ring_id": r.ring_id,
                        "ring_type": r.ring_type,
                        "accounts": r.accounts[:5],  # Limit for display
                        "account_count": len(r.accounts),
                        "total_volume": r.total_volume,
                        "risk_score": r.risk_score,
                        "detection_time": r.detection_time,
                        "evidence": r.evidence[:3]
                    }
                    for r in self.detected_rings[-10:]
                ]
            }
    
    def get_account_risk(self, account_id: str) -> Optional[Dict]:
        """Get risk profile for a specific account."""
        with self.lock:
            if account_id not in self.accounts:
                return None
            
            node = self.accounts[account_id]
            return {
                "account_id": account_id,
                "risk_score": node.risk_score,
                "total_sent": node.total_sent,
                "total_received": node.total_received,
                "transaction_count": node.transaction_count,
                "velocity": node.velocity(),
                "connected_accounts": len(node.connected_accounts),
                "flags": node.flags,
                "in_rings": [r.ring_id for r in self.detected_rings if account_id in r.accounts]
            }
    
    def get_graph_data(self, max_nodes: int = 100) -> Dict:
        """Get graph data for visualization."""
        with self.lock:
            # Get most interesting nodes (highest risk or most connections)
            sorted_accounts = sorted(
                self.accounts.values(),
                key=lambda a: (a.risk_score, len(a.connected_accounts)),
                reverse=True
            )[:max_nodes]
            
            node_ids = {a.account_id for a in sorted_accounts}
            
            nodes = [
                {
                    "id": a.account_id,
                    "risk_score": a.risk_score,
                    "volume": a.total_sent + a.total_received,
                    "flags": a.flags[:3],
                    "in_ring": any(a.account_id in r.accounts for r in self.active_rings.values())
                }
                for a in sorted_accounts
            ]
            
            links = []
            seen_links = set()
            
            for edge in self.edges[-500:]:  # Recent edges
                if edge.from_account in node_ids and edge.to_account in node_ids:
                    link_key = f"{edge.from_account}->{edge.to_account}"
                    if link_key not in seen_links:
                        seen_links.add(link_key)
                        links.append({
                            "source": edge.from_account,
                            "target": edge.to_account,
                            "amount": edge.amount,
                            "suspicious": len(edge.flags) > 0
                        })
            
            return {
                "nodes": nodes,
                "links": links,
                "rings": [
                    {"accounts": r.accounts, "type": r.ring_type}
                    for r in list(self.active_rings.values())[:5]
                ]
            }


# Global instance
fraud_detector = FraudRingDetector()
