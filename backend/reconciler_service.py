from datetime import datetime, timedelta, timezone
from collections import defaultdict
import json
import random
import time
import threading
import requests
import csv
import io
import logging
from flask import Flask, request, jsonify, Response
from flask_socketio import SocketIO
from flask_cors import CORS
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable, KafkaError
from typing import Optional, Any
from sqlalchemy import create_engine, Column, String, Float, Integer, JSON, func, text, text
from sqlalchemy.orm import sessionmaker, declarative_base, Mapped, mapped_column
import jwt
from kafka_config import build_kafka_common_kwargs, load_kafka_settings, validate_event_hubs_kafka_settings
from foundry_responses_client import generate_reconciliation_insight, foundry_is_configured, probe_foundry_status

import os
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

WEBHOOK_URL = "YOUR_DISCORD_OR_SLACK_WEBHOOK_URL" 

KAFKA_SETTINGS = load_kafka_settings()


def _redact_endpoint(endpoint: Optional[str]) -> Optional[str]:
    if not endpoint:
        return None
    try:
        parsed = urlparse(endpoint)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return endpoint
    except Exception:
        return endpoint


AI_RUNTIME = {
    "configured": foundry_is_configured(),
    "endpoint": _redact_endpoint(os.getenv("AZURE_FOUNDRY_ENDPOINT")),
    "deployment": (os.getenv("AZURE_FOUNDRY_DEPLOYMENT") or "").strip() or None,
    "last_ok": None,
    "last_error": None,
    "last_trace_id": None,
    "last_updated_at": None,
    "last_probe": None,
    "last_probe_at": None,
}


def _record_ai_runtime(trace_id: str, insight: dict) -> None:
    AI_RUNTIME["configured"] = foundry_is_configured()
    AI_RUNTIME["last_trace_id"] = trace_id
    AI_RUNTIME["last_updated_at"] = time.time()
    if insight.get("ok") is True:
        AI_RUNTIME["last_ok"] = True
        AI_RUNTIME["last_error"] = None
        return
    if insight.get("enabled") is False:
        AI_RUNTIME["last_ok"] = False
        AI_RUNTIME["last_error"] = insight.get("error_code") or insight.get("error")
        return
    AI_RUNTIME["last_ok"] = False
    AI_RUNTIME["last_error"] = insight.get("error_code") or insight.get("error_type") or insight.get("error")


def _log_ai_insight(trace_id: str, insight: dict) -> None:
    if insight.get("ok") is True:
        logger.info(f"🧠 Foundry Responses insight OK for tx_id={trace_id}")
        return

    # Distinguish not configured vs runtime error.
    if insight.get("enabled") is False:
        logger.warning(f"🧠 Foundry Responses DISABLED for tx_id={trace_id}: {insight.get('error_code') or insight.get('error')}")
        return

    status_code = insight.get("status_code")
    error_type = insight.get("error_type") or insight.get("error_code") or insight.get("error")
    hint = insight.get("hint")
    if hint:
        logger.warning(
            f"🧠 Foundry Responses FAILED for tx_id={trace_id}: {error_type} (status={status_code}) | {hint}"
        )
    else:
        logger.warning(f"🧠 Foundry Responses FAILED for tx_id={trace_id}: {error_type} (status={status_code})")


def _probe_ai_cached(ttl_seconds: int = 30) -> dict:
    """Probe Foundry endpoint auth + deployment existence with a small Responses call.

    Cached to avoid unnecessary token spend and noisy health polling.
    """

    now = time.time()
    last_at = AI_RUNTIME.get("last_probe_at")
    if isinstance(last_at, (int, float)) and (now - last_at) < ttl_seconds and AI_RUNTIME.get("last_probe"):
        return AI_RUNTIME["last_probe"]

    result = probe_foundry_status()
    AI_RUNTIME["last_probe"] = result
    AI_RUNTIME["last_probe_at"] = now
    return result


def _ai_remote_allowed() -> bool:
    """Avoid hammering Foundry when we already know auth/deployment is misconfigured."""

    if not foundry_is_configured():
        return False

    probe = _probe_ai_cached()
    if probe.get("ok") is True:
        return True

    # Fatal misconfig: don't retry on every mismatch.
    if probe.get("error_code") in {"AUTHENTICATION_MISCONFIG", "DEPLOYMENT_MISMATCH"}:
        return False

    # Transient/unknown errors: allow attempts (caller will handle failures).
    return True


def _ai_skipped_payload(trace_id: str) -> dict:
    probe = _probe_ai_cached()
    return {
        "enabled": True,
        "ok": False,
        "analysis": None,
        "raw": None,
        "status_code": None,
        "error_code": "AI_SKIPPED_DUE_TO_PROBE",
        "error_type": None,
        "hint": probe,
        "generated_at": time.time(),
    }

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super_secret_cybersecurity_key_123' 
CORS(app) 
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)

# Connection state tracking
CONNECTION_STATE = {
    "kafka_connected": False,
    "kafka_last_error": None,
    "kafka_reconnect_attempts": 0,
    "last_message_time": None,
    "uptime_start": time.time()
}

# Global Settings
SYSTEM_SETTINGS = {
    "auto_mitigation": True,
    "risk_threshold": 80,
    "sound_alerts": True
}

# Chaos Controller (starts running by default)
CHAOS_CONTROL = {
    "running": True,
    "speed": 1.0,  # Transactions per second
    "chaos_rate": 40  # % of transactions that have issues
}

# Statistics tracking
STATS_TRACKER = {
    "hourly_mismatches": defaultdict(int),
    "daily_mismatches": defaultdict(int),
    "mismatch_types": defaultdict(int),
    "country_risks": defaultdict(lambda: {"total": 0, "mismatches": 0}),
    "resolution_times": [],
    "start_time": time.time()
}

Base = declarative_base()
engine = create_engine('sqlite:///banking_ledger.db', echo=False) 

class Transaction(Base):
    __tablename__ = 'transactions'
    tx_id: Mapped[str] = mapped_column(String, primary_key=True)
    pg_data: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    cbs_data: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    mobile_data: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # NEW: Mobile Banking data
    status: Mapped[str] = mapped_column(String, default="PENDING") 
    mismatch_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Track mismatch category
    timestamp: Mapped[float] = mapped_column(Float)
    resolved_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Track resolution time


class AiInsight(Base):
    __tablename__ = 'ai_insights'
    tx_id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def upsert_ai_insight(session, tx_id: str, payload: dict) -> None:
    existing = session.query(AiInsight).filter_by(tx_id=tx_id).first()
    if existing is None:
        session.add(AiInsight(tx_id=tx_id, payload=payload, created_at=time.time()))
    else:
        existing.payload = payload
        existing.created_at = time.time()
    session.commit()


def get_ai_insight(session, tx_id: str) -> Optional[dict]:
    row = session.query(AiInsight).filter_by(tx_id=tx_id).first()
    if row and row.payload:
        return row.payload
    return None



def send_ops_alert(title, message, color):
    """Sends a real notification to a team chat (Discord/Slack)."""
    if "YOUR_DISCORD" in WEBHOOK_URL: return 
    
    data = {
        "username": "LedgerFlow Bot",
        "embeds": [{
            "title": title,
            "description": message,
            "color": color 
        }]
    }
    try:
        requests.post(WEBHOOK_URL, json=data)
    except:
        pass

def get_kafka_consumer():
    """Create Kafka consumer with retry logic."""
    max_retries = 5
    retry_delay = 2

    validation_error = validate_event_hubs_kafka_settings(KAFKA_SETTINGS)
    if validation_error:
        CONNECTION_STATE["kafka_connected"] = False
        CONNECTION_STATE["kafka_last_error"] = validation_error
        logger.error(f"❌ Kafka/Event Hubs configuration error: {validation_error}")
        socketio.emit(
            'system_status',
            {'kafka_connected': False, 'message': 'Kafka misconfigured', 'error': validation_error},
        )
        return None

    def _wait_for_broker_metadata(consumer: KafkaConsumer, timeout_seconds: float = 5.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                client = getattr(consumer, "_client", None)
                cluster = getattr(client, "cluster", None) if client else None
                brokers = cluster.brokers() if cluster else []
                if brokers:
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False
    
    for attempt in range(max_retries):
        try:
            topics = KAFKA_SETTINGS.topics
            consumer_kwargs = {
                **build_kafka_common_kwargs(KAFKA_SETTINGS),
                "value_deserializer": lambda m: json.loads(m.decode('utf-8')),
                "auto_offset_reset": 'latest',
                "group_id": KAFKA_SETTINGS.group_id,
                "consumer_timeout_ms": 10000,  # 10 second timeout for graceful reconnection
                "session_timeout_ms": 30000,
                "heartbeat_interval_ms": 10000,
            }
            consumer = KafkaConsumer(*topics, **consumer_kwargs)

            if not _wait_for_broker_metadata(consumer):
                # Treat as not connected; this commonly happens when SASL auth fails.
                raise NoBrokersAvailable(
                    "Connected socket but no broker metadata received. Check SASL credentials and Event Hubs configuration."
                )

            CONNECTION_STATE["kafka_connected"] = True
            CONNECTION_STATE["kafka_last_error"] = None
            CONNECTION_STATE["kafka_reconnect_attempts"] = 0
            logger.info(f"✅ Successfully connected to Kafka at {KAFKA_SETTINGS.bootstrap_servers}")
            socketio.emit('system_status', {'kafka_connected': True, 'message': 'Kafka connected'})
            return consumer
        except NoBrokersAvailable as e:
            CONNECTION_STATE["kafka_connected"] = False
            CONNECTION_STATE["kafka_last_error"] = str(e)
            CONNECTION_STATE["kafka_reconnect_attempts"] = attempt + 1
            logger.warning(f"⚠️ Kafka connection attempt {attempt + 1}/{max_retries} failed: {e}")
            socketio.emit('system_status', {'kafka_connected': False, 'message': f'Connecting to Kafka... (attempt {attempt + 1})'})
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
        except Exception as e:
            CONNECTION_STATE["kafka_connected"] = False
            CONNECTION_STATE["kafka_last_error"] = str(e)
            logger.error(f"❌ Unexpected Kafka error: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    
    return None

def get_ai_analysis(pg, cbs, mobile=None):
    """
    Enhanced AI model analyzing the discrepancy across all three sources.
    Returns: (Analysis String, Risk Score 0-100, Mismatch Type)
    """
    sources_present = sum([1 for s in [pg, cbs, mobile] if s])
    
    if sources_present == 1:
        return "CRITICAL DATA LOSS: Transaction exists in only one system. Severe synchronization failure.", 95, "DATA_LOSS"
    
    if not cbs:
        return "CBS BLACKHOLE: Transaction vanished in Core Banking. Potential database failure or network partition.", 90, "MISSING_CBS"
    
    if not mobile:
        return "MOBILE SYNC FAILURE: Transaction not replicated to mobile banking. API gateway issue likely.", 60, "MISSING_MOBILE"
    
    # Compare amounts across all available sources
    amounts = [s['amount'] for s in [pg, cbs, mobile] if s]
    if len(set(amounts)) > 1:
        max_diff = max(amounts) - min(amounts)
        ratio = max_diff / min(amounts) if min(amounts) > 0 else 0
        
        if ratio > 10.0:
            return "🚨 FRAUD ALERT: Massive amount discrepancy across systems. High probability of injection attack or internal fraud.", 100, "FRAUD"
        elif ratio > 1.0:
            return "SIGNIFICANT VARIANCE: Large amount mismatch detected. Possible currency conversion error or duplicate posting.", 75, "AMOUNT_MISMATCH"
        elif ratio > 0.0:
            return "SKIMMING DETECTED: Small amount variance. Possible rounding error, fee miscalculation, or malicious skimming.", 40, "SKIMMING"
    
    # Compare statuses
    statuses = [s['status'] for s in [pg, cbs, mobile] if s]
    if len(set(statuses)) > 1:
        return "STATE DRIFT: Transaction status mismatch across systems. Race condition or webhook latency detected.", 30, "STATUS_MISMATCH"
    
    # Compare timestamps
    timestamps = [s['timestamp'] for s in [pg, cbs, mobile] if s]
    if max(timestamps) - min(timestamps) > 5.0:
        return "TIMESTAMP DRIFT: Significant time difference between system records. Network latency or clock skew.", 20, "TIMESTAMP_DRIFT"
        
    return "Unknown Anomaly", 50, "UNKNOWN"

def emit_alert(txn_data, message, severity, analysis=None, risk_score=0, mismatch_type=None, ai=None):
    if not txn_data: return
    
    country = txn_data.get('country', 'Unknown')
    
    # Track statistics
    current_hour = datetime.now().strftime('%Y-%m-%d %H:00')
    current_day = datetime.now().strftime('%Y-%m-%d')
    
    if severity in ['error', 'warning']:
        STATS_TRACKER["hourly_mismatches"][current_hour] += 1
        STATS_TRACKER["daily_mismatches"][current_day] += 1
        STATS_TRACKER["country_risks"][country]["mismatches"] += 1
        if mismatch_type:
            STATS_TRACKER["mismatch_types"][mismatch_type] += 1
    
    STATS_TRACKER["country_risks"][country]["total"] += 1
    
    payload = {
        'id': txn_data['transaction_id'],
        'message': message,
        'severity': severity,
        'amount': txn_data['amount'],
        'currency': txn_data.get('currency', 'INR'),
        'timestamp': time.strftime('%H:%M:%S'),
        'analysis': analysis,
        'risk_score': risk_score,
        'country': country,
        'city': txn_data.get('city', 'Unknown'),
        'type': txn_data.get('type', 'TRANSFER'),
        'channel': txn_data.get('channel', 'WEB'),
        'mismatch_type': mismatch_type,
        'sound_alert': SYSTEM_SETTINGS["sound_alerts"] and severity == 'error',
        'ai': ai,
    }
    socketio.emit('new_alert', payload)

def auto_mitigate(session, txn, issue_type):
    """Automatically attempts to fix the discrepancy using 3-way reconciliation logic."""
    if not SYSTEM_SETTINGS["auto_mitigation"]:
        return False

    time.sleep(0.5) # Simulate processing time
    
    if issue_type == 'AMOUNT_MISMATCH':
        # Use majority voting - if 2 out of 3 sources agree, use that value
        amounts = []
        if txn.pg_data: amounts.append(('pg', txn.pg_data['amount']))
        if txn.cbs_data: amounts.append(('cbs', txn.cbs_data['amount']))
        if txn.mobile_data: amounts.append(('mobile', txn.mobile_data['amount']))
        
        # Find consensus amount
        amount_counts = defaultdict(list)
        for source, amt in amounts:
            amount_counts[amt].append(source)
        
        # Get the amount with most votes
        consensus_amount = max(amount_counts.items(), key=lambda x: len(x[1]))[0]
        
        if txn.cbs_data:
            new_cbs = dict(txn.cbs_data)
            new_cbs['amount'] = consensus_amount
            txn.cbs_data = new_cbs
        if txn.mobile_data:
            new_mobile = dict(txn.mobile_data)
            new_mobile['amount'] = consensus_amount
            txn.mobile_data = new_mobile
            
        txn.status = "AUTO_RESOLVED"
        txn.resolved_at = time.time()
        session.commit()
        
        resolution_time = txn.resolved_at - txn.timestamp
        STATS_TRACKER["resolution_times"].append(resolution_time)
        
        emit_alert(txn.pg_data, "🤖 AUTO-MITIGATED: Amount Aligned via Consensus", "success", 
                  f"System used {len(amount_counts[consensus_amount])}-way consensus to resolve discrepancy.", 0)
        return True

    elif issue_type == 'STATUS_MISMATCH':
        # Trust PG as source of truth for status
        target_status = txn.pg_data['status'] if txn.pg_data else 'SUCCESS'
        
        if txn.cbs_data:
            new_cbs = dict(txn.cbs_data)
            new_cbs['status'] = target_status
            txn.cbs_data = new_cbs
        if txn.mobile_data:
            new_mobile = dict(txn.mobile_data)
            new_mobile['status'] = target_status
            txn.mobile_data = new_mobile
            
        txn.status = "AUTO_RESOLVED"
        txn.resolved_at = time.time()
        session.commit()
        emit_alert(txn.pg_data, "🤖 AUTO-MITIGATED: Status Synchronized", "success", 
                  "System propagated authoritative status from Payment Gateway.", 0)
        return True
        
    elif issue_type in ['MISSING_CBS', 'MISSING_MOBILE']:
        # Replay transaction to missing system
        source_data = txn.pg_data or txn.cbs_data or txn.mobile_data
        
        if issue_type == 'MISSING_CBS':
            txn.cbs_data = source_data
        else:
            txn.mobile_data = source_data
            
        txn.status = "AUTO_RESOLVED"
        txn.resolved_at = time.time()
        session.commit()
        emit_alert(source_data, f"🤖 AUTO-MITIGATED: Replayed to {issue_type.split('_')[1]}", "success", 
                  "Transaction re-injected into missing system.", 0)
        return True
        
    return False

def reconcile_transaction(session, tx_id):
    """Enhanced 3-way reconciliation logic comparing PG, CBS, and Mobile data."""
    txn = session.query(Transaction).filter_by(tx_id=tx_id).first()
    
    if not txn: return None, None, None, 0
    
    pg = txn.pg_data
    cbs = txn.cbs_data
    mobile = txn.mobile_data
    
    # Need at least 2 sources to reconcile
    sources_present = sum([1 for s in [pg, cbs, mobile] if s])
    if sources_present < 2:
        return None, None, None, 0  # Wait for more data
    
    primary_data = pg or cbs or mobile
    
    # Check for amount mismatches across all sources
    amounts = [s['amount'] for s in [pg, cbs, mobile] if s]
    if len(set(amounts)) > 1:
        txn.status = "MISMATCH"
        txn.mismatch_type = "AMOUNT"
        session.commit()
        analysis, risk, mtype = get_ai_analysis(pg, cbs, mobile)
        if _ai_remote_allowed():
            insight = generate_reconciliation_insight(
                trace_id=tx_id,
                primary_txn=primary_data or {},
                mismatch_context={
                    "rule_analysis": analysis,
                    "risk_score": risk,
                    "mismatch_type": mtype,
                    "sources_present": sources_present,
                    "amounts": amounts,
                },
            )
        else:
            insight = _ai_skipped_payload(tx_id)
        _record_ai_runtime(tx_id, insight)
        _log_ai_insight(tx_id, insight)
        upsert_ai_insight(session, tx_id, insight)
        emit_alert(primary_data, "⚠️ CRITICAL: AMOUNT MISMATCH DETECTED", "error", analysis, risk, mtype, ai=insight)
        auto_mitigate(session, txn, 'AMOUNT_MISMATCH')
        return None, None, None, 0
    
    # Check for status mismatches
    statuses = [s['status'] for s in [pg, cbs, mobile] if s]
    if len(set(statuses)) > 1:
        txn.status = "WARNING"
        txn.mismatch_type = "STATUS"
        session.commit()
        analysis, risk, mtype = get_ai_analysis(pg, cbs, mobile)
        if _ai_remote_allowed():
            insight = generate_reconciliation_insight(
                trace_id=tx_id,
                primary_txn=primary_data or {},
                mismatch_context={
                    "rule_analysis": analysis,
                    "risk_score": risk,
                    "mismatch_type": mtype,
                    "sources_present": sources_present,
                    "statuses": statuses,
                },
            )
        else:
            insight = _ai_skipped_payload(tx_id)
        _record_ai_runtime(tx_id, insight)
        _log_ai_insight(tx_id, insight)
        upsert_ai_insight(session, tx_id, insight)
        emit_alert(primary_data, "⚠️ STATE ERROR: Status Mismatch", "warning", analysis, risk, mtype, ai=insight)
        auto_mitigate(session, txn, 'STATUS_MISMATCH')
        return None, None, None, 0
    
    # Check for timestamp drift
    timestamps = [s['timestamp'] for s in [pg, cbs, mobile] if s]
    if max(timestamps) - min(timestamps) > 5.0:
        txn.status = "WARNING"
        txn.mismatch_type = "TIMESTAMP"
        session.commit()
        analysis = "Significant latency detected between system records."
        if _ai_remote_allowed():
            insight = generate_reconciliation_insight(
                trace_id=tx_id,
                primary_txn=primary_data or {},
                mismatch_context={
                    "rule_analysis": analysis,
                    "risk_score": 20,
                    "mismatch_type": "TIMESTAMP_DRIFT",
                    "sources_present": sources_present,
                    "timestamps": timestamps,
                },
            )
        else:
            insight = _ai_skipped_payload(tx_id)
        _record_ai_runtime(tx_id, insight)
        _log_ai_insight(tx_id, insight)
        upsert_ai_insight(session, tx_id, insight)
        emit_alert(primary_data, "⚠️ TIMEOUT: Timestamp Drift > 5s", "warning", analysis, 20, "TIMESTAMP_DRIFT", ai=insight)
        return None, None, None, 0

    # All checks passed - transaction is reconciled
    txn.status = "MATCHED"
    txn.resolved_at = time.time()
    session.commit()
    return "✅ 3-WAY MATCH VERIFIED", "success", "Transaction Verified Across All Systems", 0

def check_missing_transactions():
    """Finds 'Phantom' transactions stuck in PENDING for too long across all 3 sources."""
    session = Session()
    current_time = time.time()
    
    stuck_txns = session.query(Transaction).filter(
        Transaction.status == "PENDING",
        Transaction.timestamp < (current_time - 5)
    ).all()
    
    for txn in stuck_txns:
        primary_data = txn.pg_data or txn.cbs_data or txn.mobile_data
        
        missing_systems = []
        if txn.cbs_data is None:
            missing_systems.append("CBS")
        if txn.mobile_data is None:
            missing_systems.append("MOBILE")
        if txn.pg_data is None:
            missing_systems.append("PG")
        
        if len(missing_systems) >= 2:
            # Critical: Missing in multiple systems
            txn.status = "CRITICAL_MISSING"
            txn.mismatch_type = "MULTI_MISSING"
            analysis, risk, mtype = get_ai_analysis(txn.pg_data, txn.cbs_data, txn.mobile_data)
            if _ai_remote_allowed():
                insight = generate_reconciliation_insight(
                    trace_id=txn.tx_id,
                    primary_txn=primary_data or {},
                    mismatch_context={
                        "rule_analysis": analysis,
                        "risk_score": risk,
                        "mismatch_type": mtype,
                        "missing_systems": missing_systems,
                    },
                )
            else:
                insight = _ai_skipped_payload(txn.tx_id)
            _record_ai_runtime(txn.tx_id, insight)
            _log_ai_insight(txn.tx_id, insight)
            upsert_ai_insight(session, txn.tx_id, insight)
            emit_alert(primary_data, f"🔥 CRITICAL: Missing in {', '.join(missing_systems)}", "error", analysis, risk, mtype, ai=insight)
            send_ops_alert("Multi-System Data Loss", f"Transaction {txn.tx_id} missing in {missing_systems}", 15158332)
            
        elif not txn.cbs_data:
            txn.status = "MISSING_CBS"
            txn.mismatch_type = "MISSING_CBS"
            analysis, risk, mtype = get_ai_analysis(txn.pg_data, None, txn.mobile_data)
            if _ai_remote_allowed():
                insight = generate_reconciliation_insight(
                    trace_id=txn.tx_id,
                    primary_txn=primary_data or {},
                    mismatch_context={
                        "rule_analysis": analysis,
                        "risk_score": risk,
                        "mismatch_type": mtype,
                        "missing_systems": ["CBS"],
                    },
                )
            else:
                insight = _ai_skipped_payload(txn.tx_id)
            _record_ai_runtime(txn.tx_id, insight)
            _log_ai_insight(txn.tx_id, insight)
            upsert_ai_insight(session, txn.tx_id, insight)
            emit_alert(primary_data, "❌ MISSING IN CBS (Core Banking Data Loss)", "error", analysis, risk, mtype, ai=insight)
            send_ops_alert("Data Loss Detected", f"Transaction {txn.tx_id} missing in Core Banking", 15158332)
            auto_mitigate(session, txn, 'MISSING_CBS')
            
        elif not txn.mobile_data:
            txn.status = "MISSING_MOBILE"
            txn.mismatch_type = "MISSING_MOBILE"
            analysis = "Transaction not replicated to mobile banking system."
            if _ai_remote_allowed():
                insight = generate_reconciliation_insight(
                    trace_id=txn.tx_id,
                    primary_txn=primary_data or {},
                    mismatch_context={
                        "rule_analysis": analysis,
                        "risk_score": 60,
                        "mismatch_type": "MISSING_MOBILE",
                        "missing_systems": ["MOBILE"],
                    },
                )
            else:
                insight = _ai_skipped_payload(txn.tx_id)
            _record_ai_runtime(txn.tx_id, insight)
            _log_ai_insight(txn.tx_id, insight)
            upsert_ai_insight(session, txn.tx_id, insight)
            emit_alert(primary_data, "📱 MISSING IN MOBILE (Sync Failure)", "warning", analysis, 60, "MISSING_MOBILE", ai=insight)
            auto_mitigate(session, txn, 'MISSING_MOBILE')
            
        elif not txn.pg_data:
            txn.status = "MISSING_PG"
            txn.mismatch_type = "GHOST"
            analysis = "Transaction exists in downstream systems but not in Payment Gateway. Potential injection."
            if _ai_remote_allowed():
                insight = generate_reconciliation_insight(
                    trace_id=txn.tx_id,
                    primary_txn=primary_data or {},
                    mismatch_context={
                        "rule_analysis": analysis,
                        "risk_score": 85,
                        "mismatch_type": "GHOST",
                        "missing_systems": ["PG"],
                    },
                )
            else:
                insight = _ai_skipped_payload(txn.tx_id)
            _record_ai_runtime(txn.tx_id, insight)
            _log_ai_insight(txn.tx_id, insight)
            upsert_ai_insight(session, txn.tx_id, insight)
            emit_alert(primary_data, "👻 GHOST TRANSACTION (Missing in PG)", "error", analysis, 85, "GHOST", ai=insight)

        session.commit()
    session.close()

def consumer_loop():
    """Resilient consumer loop with auto-reconnection."""
    logger.info("🎧 Enterprise 3-Way Reconciler starting...")
    logger.info(f"📊 Will listen on: {', '.join(KAFKA_SETTINGS.topics)}")
    if AI_RUNTIME["configured"]:
        logger.info(
            f"🧠 Foundry Responses ENABLED | endpoint={AI_RUNTIME['endpoint']} | deployment={AI_RUNTIME['deployment']}"
        )
    else:
        logger.warning(
            "🧠 Foundry Responses DISABLED | set AZURE_FOUNDRY_ENDPOINT, AZURE_FOUNDRY_API_KEY, AZURE_FOUNDRY_DEPLOYMENT"
        )
    
    while True:
        consumer = get_kafka_consumer()
        
        if consumer is None:
            logger.error("❌ Failed to connect to Kafka after multiple attempts. Retrying in 10 seconds...")
            socketio.emit('system_status', {
                'kafka_connected': False, 
                'message': 'Kafka unavailable - retrying...',
                'error': CONNECTION_STATE["kafka_last_error"]
            })
            time.sleep(10)
            continue
        
        logger.info("🎧 Connected to Kafka, processing messages...")
        
        try:
            while True:
                # Poll for messages with timeout
                messages = consumer.poll(timeout_ms=1000)
                
                if not messages:
                    # No messages, but connection is alive - send heartbeat
                    continue
                
                for topic_partition, records in messages.items():
                    for message in records:
                        try:
                            session = Session()
                            data = message.value
                            tx_id = data['transaction_id']
                            
                            CONNECTION_STATE["last_message_time"] = time.time()
                            
                            # Determine source from topic
                            pg_topic, cbs_topic, mobile_topic = KAFKA_SETTINGS.topics
                            if message.topic == pg_topic:
                                source = 'pg'
                            elif message.topic == cbs_topic:
                                source = 'cbs'
                            else:
                                source = 'mobile'

                            txn_record = session.query(Transaction).filter_by(tx_id=tx_id).first()
                            
                            if not txn_record:
                                txn_record = Transaction(tx_id=tx_id, timestamp=time.time())
                                session.add(txn_record)
                            
                            # Store data based on source
                            if source == 'pg':
                                txn_record.pg_data = data
                            elif source == 'cbs':
                                txn_record.cbs_data = data
                            else:
                                txn_record.mobile_data = data
                                
                            session.commit()
                            
                            # Run reconciliation
                            status_msg, severity, analysis, risk = reconcile_transaction(session, tx_id)
                            if status_msg:
                                emit_alert(data, status_msg, severity, analysis, risk)

                            session.close()
                            
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
                            if session:
                                session.rollback()
                                session.close()
                
                # Periodically check for stuck transactions
                if int(time.time()) % 5 == 0: 
                    check_missing_transactions()
                    
        except KafkaError as e:
            logger.error(f"❌ Kafka error in consumer loop: {e}")
            CONNECTION_STATE["kafka_connected"] = False
            CONNECTION_STATE["kafka_last_error"] = str(e)
            socketio.emit('system_status', {'kafka_connected': False, 'message': 'Kafka connection lost, reconnecting...'})
        except Exception as e:
            logger.error(f"❌ Unexpected error in consumer loop: {e}")
            CONNECTION_STATE["kafka_connected"] = False
        finally:
            try:
                consumer.close()
            except:
                pass
            logger.info("🔄 Reconnecting to Kafka in 5 seconds...")
            time.sleep(5)



def token_required(f):
    def decorator(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 403
        try:
            
            if "Bearer" in token: token = token.split(" ")[1]
            jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        except:
            return jsonify({'message': 'Token is invalid!'}), 403
        return f(*args, **kwargs)
    decorator.__name__ = f.__name__
    return decorator

@app.route('/api/login', methods=['POST'])
def login():
    auth = request.json
    
    if auth and auth['username'] == 'admin' and auth['password'] == 'securePass123!':
        token = jwt.encode({
            'user': 'admin',
            'exp': datetime.now(timezone.utc) + timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm="HS256")
        return jsonify({'token': token})
    return jsonify({'message': 'Could not verify'}), 401

@app.route('/api/stats', methods=['GET'])
def get_stats():
    session = Session()
    total = session.query(Transaction).count()
    matched = session.query(Transaction).filter(Transaction.status == 'MATCHED').count()
    auto_resolved = session.query(Transaction).filter(Transaction.status == 'AUTO_RESOLVED').count()
    mismatches = session.query(Transaction).filter(Transaction.status.in_(
        ['MISMATCH', 'WARNING', 'MISSING_CBS', 'MISSING_PG', 'MISSING_MOBILE', 'CRITICAL_MISSING']
    )).count()
    
    # Calculate match rate
    match_rate = ((matched + auto_resolved) / total * 100) if total > 0 else 100
    
    # Calculate average resolution time
    avg_resolution = sum(STATS_TRACKER["resolution_times"][-100:]) / len(STATS_TRACKER["resolution_times"][-100:]) \
        if STATS_TRACKER["resolution_times"] else 0
    
    # Calculate transactions per minute
    uptime_minutes = (time.time() - STATS_TRACKER["start_time"]) / 60
    tpm = int(total / uptime_minutes) if uptime_minutes > 0 else 0
    
    session.close()
    return jsonify({
        'total_processed': total,
        'total_matched': matched,
        'total_auto_resolved': auto_resolved,
        'total_issues': mismatches,
        'match_rate': round(match_rate, 1),
        'health_score': max(0, 100 - (mismatches * 2)), 
        'tpm': tpm,
        'avg_resolution_time': round(avg_resolution, 2),
        'uptime_minutes': round(uptime_minutes, 1)
    })

@app.route('/api/heatmap', methods=['GET'])
def get_heatmap():
    """Generates real heatmap data based on actual database mismatches."""
    session = Session()
    
    # Get real mismatches from database grouped by day/hour
    heatmap_data = []
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Query actual transactions from the database
    all_txns = session.query(Transaction).filter(
        Transaction.status != 'MATCHED'
    ).all()
    
    # Build counts matrix
    counts = {day: {hour: 0 for hour in range(24)} for day in days}
    
    for txn in all_txns:
        dt = datetime.fromtimestamp(txn.timestamp)
        day_name = days[dt.weekday()]
        hour = dt.hour
        counts[day_name][hour] += 1
    
    # Format for frontend
    for day in days:
        day_data: dict[str, str | int] = {'day': day}
        for hour in range(24):
            day_data[f'h{hour}'] = counts[day][hour]
        heatmap_data.append(day_data)
    
    session.close()
    return jsonify(heatmap_data)

@app.route('/api/geo-risk', methods=['GET'])
def get_geo_risk():
    """Returns geographic risk data for world map visualization."""
    geo_data = []
    for country, data in STATS_TRACKER["country_risks"].items():
        if data["total"] > 0:
            risk_rate = (data["mismatches"] / data["total"]) * 100
            geo_data.append({
                'country': country,
                'total': data["total"],
                'mismatches': data["mismatches"],
                'risk_rate': round(risk_rate, 1)
            })
    
    # Sort by risk rate descending
    geo_data.sort(key=lambda x: x['risk_rate'], reverse=True)
    return jsonify(geo_data)

@app.route('/api/mismatch-types', methods=['GET'])
def get_mismatch_types():
    """Returns breakdown of mismatch types for pie chart."""
    return jsonify(dict(STATS_TRACKER["mismatch_types"]))


# ==================== CHAOS PRODUCER CONTROL APIs ====================
# Note: These endpoints don't require authentication for easier control

@app.route('/api/chaos/status', methods=['GET'])
def chaos_status():
    """Get current chaos producer status (no auth required)."""
    return jsonify(CHAOS_CONTROL)


@app.route('/api/health', methods=['GET'])
def health_check():
    """Comprehensive health check endpoint."""
    session = Session()
    try:
        # Test database connection
        session.execute(text("SELECT 1"))
        db_healthy = True
    except:
        db_healthy = False
    finally:
        session.close()
    
    uptime = time.time() - CONNECTION_STATE["uptime_start"]
    hours, remainder = divmod(int(uptime), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return jsonify({
        'status': 'healthy' if (db_healthy and CONNECTION_STATE["kafka_connected"]) else 'degraded',
        'kafka': {
            'connected': CONNECTION_STATE["kafka_connected"],
            'last_error': CONNECTION_STATE["kafka_last_error"],
            'reconnect_attempts': CONNECTION_STATE["kafka_reconnect_attempts"],
            'last_message': CONNECTION_STATE["last_message_time"]
        },
        'database': {
            'connected': db_healthy
        },
        'ai': {
            'configured': AI_RUNTIME.get('configured'),
            'endpoint': AI_RUNTIME.get('endpoint'),
            'deployment': AI_RUNTIME.get('deployment'),
            'last_ok': AI_RUNTIME.get('last_ok'),
            'last_error': AI_RUNTIME.get('last_error'),
            'last_trace_id': AI_RUNTIME.get('last_trace_id'),
            'last_updated_at': AI_RUNTIME.get('last_updated_at'),
            'probe': _probe_ai_cached(),
        },
        'uptime': f"{hours}h {minutes}m {seconds}s",
        'uptime_seconds': uptime
    })


@app.route('/api/ai/status', methods=['GET'])
def ai_status():
    """Health endpoint for Foundry Responses integration (no auth).

    Validates:
    - Foundry endpoint reachable
    - deployment exists
    - key authorized
    """
    probe = _probe_ai_cached()
    return jsonify({
        'configured': AI_RUNTIME.get('configured'),
        'endpoint': AI_RUNTIME.get('endpoint'),
        'deployment': AI_RUNTIME.get('deployment'),
        'last_ok': AI_RUNTIME.get('last_ok'),
        'last_error': AI_RUNTIME.get('last_error'),
        'last_trace_id': AI_RUNTIME.get('last_trace_id'),
        'last_updated_at': AI_RUNTIME.get('last_updated_at'),
        'probe': probe,
    })


@app.route('/api/chaos/start', methods=['POST'])
def chaos_start():
    """Start the chaos producer (no auth required)."""
    CHAOS_CONTROL["running"] = True
    socketio.emit('chaos_status', CHAOS_CONTROL)
    print(f"🎮 Chaos Producer: STARTED")
    return jsonify({"status": "started", **CHAOS_CONTROL})


@app.route('/api/chaos/stop', methods=['POST'])
def chaos_stop():
    """Stop the chaos producer (no auth required)."""
    CHAOS_CONTROL["running"] = False
    socketio.emit('chaos_status', CHAOS_CONTROL)
    print(f"🎮 Chaos Producer: STOPPED")
    return jsonify({"status": "stopped", **CHAOS_CONTROL})


@app.route('/api/chaos/speed', methods=['POST'])
def chaos_speed():
    """Set chaos producer speed and rate (no auth required)."""
    data = request.json
    if 'speed' in data:
        CHAOS_CONTROL["speed"] = max(0.1, min(10.0, float(data['speed'])))
    if 'chaos_rate' in data:
        CHAOS_CONTROL["chaos_rate"] = max(0, min(100, int(data['chaos_rate'])))
    socketio.emit('chaos_status', CHAOS_CONTROL)
    print(f"🎮 Chaos Settings Updated: Speed={CHAOS_CONTROL['speed']}x, Chaos Rate={CHAOS_CONTROL['chaos_rate']}%")
    return jsonify(CHAOS_CONTROL)

@app.route('/api/transaction/<tx_id>', methods=['GET'])
@token_required
def get_transaction_detail(tx_id):
    """Returns detailed comparison of a single transaction across all sources."""
    session = Session()
    txn = session.query(Transaction).filter_by(tx_id=tx_id).first()
    
    if not txn:
        session.close()
        return jsonify({'error': 'Transaction not found'}), 404
    
    result = {
        'tx_id': txn.tx_id,
        'status': txn.status,
        'mismatch_type': txn.mismatch_type,
        'timestamp': txn.timestamp,
        'resolved_at': txn.resolved_at,
        'sources': {
            'payment_gateway': txn.pg_data,
            'core_banking': txn.cbs_data,
            'mobile_banking': txn.mobile_data
        },
        'ai_insight': get_ai_insight(session, tx_id),
        'discrepancies': []
    }
    
    # Calculate discrepancies
    sources = [('PG', txn.pg_data), ('CBS', txn.cbs_data), ('Mobile', txn.mobile_data)]
    available = [(name, data) for name, data in sources if data]
    
    if len(available) >= 2:
        # Compare amounts
        amounts = {name: data['amount'] for name, data in available}
        if len(set(amounts.values())) > 1:
            result['discrepancies'].append({
                'field': 'amount',
                'values': amounts,
                'severity': 'high'
            })
        
        # Compare statuses
        statuses = {name: data['status'] for name, data in available}
        if len(set(statuses.values())) > 1:
            result['discrepancies'].append({
                'field': 'status',
                'values': statuses,
                'severity': 'medium'
            })
        
        # Compare timestamps
        timestamps = {name: data['timestamp'] for name, data in available}
        if max(timestamps.values()) - min(timestamps.values()) > 5:
            result['discrepancies'].append({
                'field': 'timestamp',
                'values': timestamps,
                'severity': 'low'
            })
    
    session.close()
    return jsonify(result)

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    if request.method == 'POST':
        data = request.json
        if 'auto_mitigation' in data:
            SYSTEM_SETTINGS['auto_mitigation'] = bool(data['auto_mitigation'])
        if 'risk_threshold' in data:
            SYSTEM_SETTINGS['risk_threshold'] = int(data['risk_threshold'])
        if 'sound_alerts' in data:
            SYSTEM_SETTINGS['sound_alerts'] = bool(data['sound_alerts'])
        return jsonify({"message": "Settings updated", "settings": SYSTEM_SETTINGS})
    
    return jsonify(SYSTEM_SETTINGS)

@app.route('/api/resolve', methods=['POST'])
@token_required
def manual_resolve():
    data = request.json
    tx_id = data.get('tx_id')
    action = data.get('action') # 'accept_pg', 'accept_cbs', 'accept_mobile', 'mark_resolved'
    
    session = Session()
    txn = session.query(Transaction).filter_by(tx_id=tx_id).first()
    
    if not txn:
        session.close()
        return jsonify({'message': 'Transaction not found'}), 404
    
    source_data = txn.pg_data or txn.cbs_data or txn.mobile_data
    
    if action == 'accept_pg' and txn.pg_data:
        txn.cbs_data = txn.pg_data
        txn.mobile_data = txn.pg_data
        txn.status = "MANUALLY_RESOLVED"
        msg = "Aligned all systems to Payment Gateway"
    elif action == 'accept_cbs' and txn.cbs_data:
        txn.pg_data = txn.cbs_data
        txn.mobile_data = txn.cbs_data
        txn.status = "MANUALLY_RESOLVED"
        msg = "Aligned all systems to Core Banking"
    elif action == 'accept_mobile' and txn.mobile_data:
        txn.pg_data = txn.mobile_data
        txn.cbs_data = txn.mobile_data
        txn.status = "MANUALLY_RESOLVED"
        msg = "Aligned all systems to Mobile Banking"
    else:
        txn.status = "MANUALLY_RESOLVED"
        msg = "Marked as resolved by operator"
    
    txn.resolved_at = time.time()
    session.commit()
    emit_alert(source_data, f"🛠️ {msg}", "success", "Operator Intervention", 0)
    session.close()
    
    return jsonify({'message': 'Transaction resolved successfully'})

import csv
import io
from flask import Flask, request, jsonify, Response

# ... existing code ...

@app.route('/api/export', methods=['GET'])
@token_required
def export_report():
    """Generates a comprehensive CSV report of all mismatched transactions."""
    session = Session()
    mismatches = session.query(Transaction).filter(Transaction.status.in_(
        ['MISMATCH', 'WARNING', 'MISSING_CBS', 'MISSING_PG', 'MISSING_MOBILE', 'CRITICAL_MISSING', 'MANUALLY_RESOLVED', 'AUTO_RESOLVED']
    )).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Transaction ID', 'Status', 'Mismatch Type', 'Timestamp', 'Resolved At',
        'PG Amount', 'CBS Amount', 'Mobile Amount',
        'PG Status', 'CBS Status', 'Mobile Status',
        'Country', 'Currency', 'Channel'
    ])
    
    for txn in mismatches:
        pg_amt = txn.pg_data.get('amount') if txn.pg_data else 'N/A'
        cbs_amt = txn.cbs_data.get('amount') if txn.cbs_data else 'N/A'
        mobile_amt = txn.mobile_data.get('amount') if txn.mobile_data else 'N/A'
        pg_stat = txn.pg_data.get('status') if txn.pg_data else 'N/A'
        cbs_stat = txn.cbs_data.get('status') if txn.cbs_data else 'N/A'
        mobile_stat = txn.mobile_data.get('status') if txn.mobile_data else 'N/A'
        
        primary_data = txn.pg_data or txn.cbs_data or txn.mobile_data or {}
        
        writer.writerow([
            txn.tx_id, txn.status, txn.mismatch_type or 'N/A', 
            txn.timestamp, txn.resolved_at or 'N/A',
            pg_amt, cbs_amt, mobile_amt,
            pg_stat, cbs_stat, mobile_stat,
            primary_data.get('country', 'N/A'),
            primary_data.get('currency', 'N/A'),
            primary_data.get('channel', 'N/A')
        ])
        
    session.close()
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=reconciliation_report.csv"}
    )

if __name__ == '__main__':
    
    threading.Thread(target=consumer_loop, daemon=True).start()
    
    
    print("🚀 LedgerFlow Engine v3.0 (3-Way Reconciliation) Live on Port 5000")
    print("📊 Features: 3-Way Matching | AI Analysis | Auto-Mitigation | Geo-Risk")
    socketio.run(app, port=5000)