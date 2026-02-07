import json
import time
import random
import requests
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable, KafkaError
from faker import Faker
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from kafka_config import build_kafka_common_kwargs, load_kafka_settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

KAFKA_SETTINGS = load_kafka_settings()
KAFKA_SERVER = KAFKA_SETTINGS.bootstrap_servers
TOPIC_PG, TOPIC_CBS, TOPIC_MOBILE = KAFKA_SETTINGS.topics
API_URL = 'http://localhost:5000'

fake = Faker('en_IN')  # Indian locale


# ============================================================================
# ADVANCED CHAOS SCENARIOS - Hackathon Special Effects
# ============================================================================

class ChaosScenario(Enum):
    """Advanced chaos scenarios for dramatic demo effects."""
    NONE = "none"
    CBS_OUTAGE = "cbs_outage"              # CBS goes completely dark
    MOBILE_OUTAGE = "mobile_outage"        # Mobile app crashes
    NETWORK_PARTITION = "network_partition" # One region goes dark
    GRADUAL_DEGRADATION = "gradual_degradation"  # CBS drifts over time
    FRAUD_RING = "fraud_ring"              # Coordinated fraud burst
    FLASH_CRASH = "flash_crash"            # Massive volume spike with errors
    DATA_CORRUPTION = "data_corruption"    # Random field corruption
    REPLAY_ATTACK = "replay_attack"        # Duplicate transactions


@dataclass
class ScenarioState:
    """Tracks state for active chaos scenarios."""
    active_scenario: ChaosScenario = ChaosScenario.NONE
    start_time: float = 0.0
    duration: float = 30.0  # Default 30 seconds
    intensity: float = 1.0  # 0.0 to 1.0
    
    # Scenario-specific state
    degradation_factor: float = 1.0  # For gradual degradation
    affected_region: Optional[str] = None  # For network partition
    fraud_ring_accounts: List[str] = field(default_factory=list)
    replay_buffer: deque = field(default_factory=lambda: deque(maxlen=10))
    
    def is_active(self) -> bool:
        if self.active_scenario == ChaosScenario.NONE:
            return False
        return time.time() - self.start_time < self.duration
    
    def time_remaining(self) -> float:
        return max(0, self.duration - (time.time() - self.start_time))
    
    def progress(self) -> float:
        """Returns 0.0 to 1.0 indicating scenario progress."""
        if not self.is_active():
            return 1.0
        elapsed = time.time() - self.start_time
        return min(1.0, elapsed / self.duration)


# Global scenario state
scenario_state = ScenarioState()
scenario_lock = threading.Lock()


def get_scenario_status() -> Dict[str, Any]:
    """Get current scenario status for API."""
    with scenario_lock:
        return {
            "active": scenario_state.is_active(),
            "scenario": scenario_state.active_scenario.value,
            "time_remaining": round(scenario_state.time_remaining(), 1),
            "progress": round(scenario_state.progress() * 100, 1),
            "intensity": scenario_state.intensity,
            "affected_region": scenario_state.affected_region
        }


def trigger_scenario(scenario_name: str, duration: float = 30.0, intensity: float = 1.0, 
                     region: Optional[str] = None) -> Dict[str, Any]:
    """Trigger a chaos scenario."""
    global scenario_state
    
    try:
        scenario = ChaosScenario(scenario_name)
    except ValueError:
        return {"success": False, "error": f"Unknown scenario: {scenario_name}"}
    
    with scenario_lock:
        scenario_state = ScenarioState(
            active_scenario=scenario,
            start_time=time.time(),
            duration=duration,
            intensity=intensity,
            affected_region=region or random.choice(list(COUNTRY_CONFIG.keys())),
            fraud_ring_accounts=[f"FRAUD{random.randint(1000, 9999)}" for _ in range(5)],
            replay_buffer=deque(maxlen=10),
            degradation_factor=1.0
        )
    
    logger.warning(f"🚨 CHAOS SCENARIO TRIGGERED: {scenario.value} for {duration}s at {intensity*100:.0f}% intensity")
    return {
        "success": True,
        "scenario": scenario.value,
        "duration": duration,
        "intensity": intensity,
        "affected_region": scenario_state.affected_region
    }


def stop_scenario() -> Dict[str, Any]:
    """Stop any active scenario."""
    global scenario_state
    
    with scenario_lock:
        old_scenario = scenario_state.active_scenario.value
        scenario_state = ScenarioState()
    
    logger.info(f"✅ Chaos scenario stopped: {old_scenario}")
    return {"success": True, "stopped": old_scenario}


def apply_scenario_effects(transaction: dict, pg_data: dict, cbs_data: Optional[dict], 
                           mobile_data: Optional[dict], original_log: str) -> tuple:
    """Apply active scenario effects to transaction data."""
    global scenario_state
    
    with scenario_lock:
        if not scenario_state.is_active():
            return pg_data, cbs_data, mobile_data, original_log
        
        scenario = scenario_state.active_scenario
        intensity = scenario_state.intensity
        progress = scenario_state.progress()
        
        # CBS Outage - CBS goes completely dark
        if scenario == ChaosScenario.CBS_OUTAGE:
            if random.random() < intensity:
                return pg_data, None, mobile_data, "💥 CBS OUTAGE - System Down"
        
        # Mobile Outage - Mobile app crashes
        elif scenario == ChaosScenario.MOBILE_OUTAGE:
            if random.random() < intensity:
                return pg_data, cbs_data, None, "📱 MOBILE OUTAGE - App Crash"
        
        # Network Partition - One region goes completely dark
        elif scenario == ChaosScenario.NETWORK_PARTITION:
            if transaction.get('country') == scenario_state.affected_region:
                if random.random() < intensity:
                    return pg_data, None, None, f"🌐 PARTITION - {scenario_state.affected_region} Isolated"
        
        # Gradual Degradation - CBS amounts drift over time
        elif scenario == ChaosScenario.GRADUAL_DEGRADATION:
            # Degradation increases over time
            scenario_state.degradation_factor = 1.0 + (progress * 0.5 * intensity)  # Up to 50% drift
            if cbs_data:
                cbs_data = cbs_data.copy()
                drift = random.uniform(0.9, 1.1) * scenario_state.degradation_factor
                cbs_data['amount'] = round(cbs_data['amount'] * drift, 2)
                if abs(drift - 1.0) > 0.1:
                    return pg_data, cbs_data, mobile_data, f"📉 DEGRADATION - CBS Drift: {(drift-1)*100:+.1f}%"
        
        # Fraud Ring - Coordinated fraud with linked accounts
        elif scenario == ChaosScenario.FRAUD_RING:
            if random.random() < intensity * 0.5:  # 50% of transactions during fraud ring
                fraud_account = random.choice(scenario_state.fraud_ring_accounts)
                pg_data = pg_data.copy()
                cbs_data = cbs_data.copy() if cbs_data else pg_data.copy()
                mobile_data = mobile_data.copy() if mobile_data else pg_data.copy()
                
                # Inflate amounts dramatically in CBS
                cbs_data['amount'] = round(pg_data['amount'] * random.uniform(10, 100), 2)
                cbs_data['user_id'] = fraud_account
                pg_data['user_id'] = fraud_account
                mobile_data['user_id'] = fraud_account
                
                return pg_data, cbs_data, mobile_data, f"🕵️ FRAUD RING - Account: {fraud_account}"
        
        # Flash Crash - Massive volume with errors
        elif scenario == ChaosScenario.FLASH_CRASH:
            error_type = random.choices(
                ['timeout', 'corruption', 'duplicate', 'missing'],
                weights=[30, 25, 25, 20]
            )[0]
            
            if error_type == 'timeout' and random.random() < intensity:
                return pg_data, None, None, "⏱️ FLASH CRASH - Timeout"
            elif error_type == 'corruption' and random.random() < intensity:
                if cbs_data:
                    cbs_data = cbs_data.copy()
                    cbs_data['amount'] = round(random.uniform(0, 1000000), 2)
                return pg_data, cbs_data, mobile_data, "💾 FLASH CRASH - Corruption"
            elif error_type == 'missing' and random.random() < intensity:
                return pg_data, None, mobile_data, "❌ FLASH CRASH - Missing"
        
        # Data Corruption - Random field corruption
        elif scenario == ChaosScenario.DATA_CORRUPTION:
            if random.random() < intensity * 0.7:
                target = random.choice(['cbs', 'mobile', 'both'])
                corruption_type = random.choice(['amount', 'status', 'timestamp', 'user_id'])
                
                if target in ['cbs', 'both'] and cbs_data:
                    cbs_data = cbs_data.copy()
                    if corruption_type == 'amount':
                        cbs_data['amount'] = round(random.uniform(0, 999999), 2)
                    elif corruption_type == 'status':
                        cbs_data['status'] = random.choice(['CORRUPTED', 'ERROR', 'NULL', '???'])
                    elif corruption_type == 'timestamp':
                        cbs_data['timestamp'] = random.uniform(0, time.time() * 2)
                    elif corruption_type == 'user_id':
                        cbs_data['user_id'] = f"CORRUPT_{random.randint(0, 999)}"
                
                if target in ['mobile', 'both'] and mobile_data:
                    mobile_data = mobile_data.copy()
                    if corruption_type == 'amount':
                        mobile_data['amount'] = round(random.uniform(0, 999999), 2)
                
                return pg_data, cbs_data, mobile_data, f"🔥 CORRUPTION - {corruption_type.upper()}"
        
        # Replay Attack - Duplicate transactions
        elif scenario == ChaosScenario.REPLAY_ATTACK:
            # Store current transaction for replay
            scenario_state.replay_buffer.append(pg_data.copy())
            
            if len(scenario_state.replay_buffer) > 3 and random.random() < intensity * 0.6:
                # Replay an old transaction
                replay_tx = random.choice(list(scenario_state.replay_buffer))
                replay_tx = replay_tx.copy()
                replay_tx['timestamp'] = time.time()  # Update timestamp
                return replay_tx, replay_tx, replay_tx, f"🔁 REPLAY ATTACK - Duplicate TX"
    
    return pg_data, cbs_data, mobile_data, original_log

def create_kafka_producer(max_retries=10, retry_delay=3):
    """Create Kafka producer with retry logic."""

    for attempt in range(max_retries):
        try:
            producer_kwargs = {
                **build_kafka_common_kwargs(KAFKA_SETTINGS),
                "value_serializer": lambda v: json.dumps(v).encode('utf-8'),
                "retries": 5,
                "retry_backoff_ms": 1000,
                "request_timeout_ms": 30000,
                "max_block_ms": 60000,
            }
            producer = KafkaProducer(**producer_kwargs)
            logger.info(f"✅ Successfully connected to Kafka at {KAFKA_SERVER}")
            return producer
        except NoBrokersAvailable as e:
            logger.warning(f"⚠️ Kafka connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                logger.info(f"🔄 Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("❌ Failed to connect to Kafka after all retries")
                raise
        except Exception as e:
            logger.error(f"❌ Unexpected error connecting to Kafka: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise

producer = None

# Multi-country configuration
COUNTRY_CONFIG = {
    'IN': {
        'weight': 40,
        'currency': 'INR',
        'banks': ['HDFC', 'ICICI', 'SBI', 'AXIS', 'KOTAK', 'PNB', 'BOB', 'IDBI', 'YES', 'CANARA'],
        'cities': ['Mumbai', 'Delhi', 'Bangalore', 'Chennai', 'Kolkata', 'Hyderabad', 'Pune', 'Ahmedabad', 'Jaipur', 'Lucknow'],
        'payment_handles': ['@ybl', '@paytm', '@okaxis', '@oksbi', '@okicici', '@apl', '@ibl'],
        'amount_range': (100, 500000),
        'locale': 'en_IN'
    },
    'US': {
        'weight': 20,
        'currency': 'USD',
        'banks': ['Chase', 'Bank of America', 'Wells Fargo', 'Citi', 'Capital One', 'US Bank', 'PNC', 'TD Bank'],
        'cities': ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia', 'San Antonio', 'San Diego'],
        'payment_handles': ['@venmo', '@cashapp', '@zelle', '@paypal'],
        'amount_range': (10, 50000),
        'locale': 'en_US'
    },
    'GB': {
        'weight': 12,
        'currency': 'GBP',
        'banks': ['Barclays', 'HSBC', 'Lloyds', 'NatWest', 'Santander UK', 'RBS', 'Halifax', 'TSB'],
        'cities': ['London', 'Manchester', 'Birmingham', 'Leeds', 'Glasgow', 'Liverpool', 'Edinburgh', 'Bristol'],
        'payment_handles': ['@monzo', '@revolut', '@starling'],
        'amount_range': (5, 25000),
        'locale': 'en_GB'
    },
    'DE': {
        'weight': 8,
        'currency': 'EUR',
        'banks': ['Deutsche Bank', 'Commerzbank', 'DZ Bank', 'KfW', 'UniCredit Germany', 'ING Germany', 'N26'],
        'cities': ['Berlin', 'Munich', 'Frankfurt', 'Hamburg', 'Cologne', 'Stuttgart', 'Düsseldorf', 'Leipzig'],
        'payment_handles': ['@n26', '@revolut', '@klarna'],
        'amount_range': (5, 30000),
        'locale': 'de_DE'
    },
    'SG': {
        'weight': 8,
        'currency': 'SGD',
        'banks': ['DBS', 'OCBC', 'UOB', 'Standard Chartered SG', 'Citibank SG', 'HSBC SG', 'Maybank SG'],
        'cities': ['Singapore Central', 'Jurong', 'Woodlands', 'Tampines', 'Bedok', 'Ang Mo Kio', 'Clementi'],
        'payment_handles': ['@paynow', '@grabpay', '@shopee'],
        'amount_range': (10, 40000),
        'locale': 'en_US'
    },
    'AE': {
        'weight': 6,
        'currency': 'AED',
        'banks': ['Emirates NBD', 'Abu Dhabi Commercial', 'Dubai Islamic', 'Mashreq', 'RAK Bank', 'First Abu Dhabi'],
        'cities': ['Dubai', 'Abu Dhabi', 'Sharjah', 'Ajman', 'Ras Al Khaimah', 'Fujairah'],
        'payment_handles': ['@neopay', '@payit', '@botim'],
        'amount_range': (50, 200000),
        'locale': 'en_US'
    },
    'AU': {
        'weight': 6,
        'currency': 'AUD',
        'banks': ['Commonwealth', 'Westpac', 'NAB', 'ANZ', 'Macquarie', 'ING Australia', 'Bendigo Bank'],
        'cities': ['Sydney', 'Melbourne', 'Brisbane', 'Perth', 'Adelaide', 'Gold Coast', 'Canberra'],
        'payment_handles': ['@osko', '@beem', '@paytm'],
        'amount_range': (10, 50000),
        'locale': 'en_AU'
    }
}

# Transaction categories
TRANSACTION_TYPES = ['TRANSFER', 'NEFT', 'IMPS', 'RTGS', 'CARD_PAYMENT', 'WALLET', 'EMI', 'BILL_PAYMENT', 'WIRE', 'ACH']
MERCHANT_CATEGORIES = ['RETAIL', 'FOOD', 'TRAVEL', 'UTILITIES', 'ENTERTAINMENT', 'HEALTHCARE', 'EDUCATION', 'E-COMMERCE']

# Legacy support
INDIAN_BANKS = COUNTRY_CONFIG['IN']['banks']
UPI_HANDLES = COUNTRY_CONFIG['IN']['payment_handles']
INDIAN_CITIES = COUNTRY_CONFIG['IN']['cities']

POLL_INTERVAL = 5

def get_chaos_status():
    try:
        res = requests.get(f'{API_URL}/api/chaos/status', timeout=1)
        if res.status_code == 200:
            data = res.json()
            # Also check for active scenario
            if 'active_scenario' in data and data['active_scenario']:
                scenario = data['active_scenario']
                # Update local scenario state
                trigger_scenario(
                    scenario.get('scenario', 'none'),
                    scenario.get('duration', 30),
                    scenario.get('intensity', 0.8),
                    scenario.get('region')
                )
            elif scenario_state.is_active():
                # Server says no scenario but we have one active - stop it
                stop_scenario()
            return data
    except requests.exceptions.RequestException:
        pass
    return {"running": True, "speed": 1.0, "chaos_rate": 40}


def select_country():
    """Select a country based on weighted distribution."""
    countries = list(COUNTRY_CONFIG.keys())
    weights = [COUNTRY_CONFIG[c]['weight'] for c in countries]
    return random.choices(countries, weights=weights, k=1)[0]


def generate_transaction():
    """Creates a transaction from a randomly selected country."""
    country = select_country()
    config = COUNTRY_CONFIG[country]
    
    # Create faker with appropriate locale
    country_fake = Faker(config['locale'])
    
    payment_handle = f"{country_fake.first_name().lower()}{random.randint(1, 999)}{random.choice(config['payment_handles'])}"
    amount_min, amount_max = config['amount_range']
    
    return {
        'transaction_id': country_fake.uuid4(),
        'user_id': f"ACC{random.randint(10000000, 99999999)}",
        'upi_id': payment_handle,
        'amount': round(random.uniform(amount_min, amount_max), 2),
        'currency': config['currency'],
        'country': country,
        'city': random.choice(config['cities']),
        'bank': random.choice(config['banks']),
        'timestamp': time.time(),
        'status': 'SUCCESS',
        'type': random.choice(TRANSACTION_TYPES),
        'merchant_category': random.choice(MERCHANT_CATEGORIES),
        'channel': random.choice(['BANK_TRANSFER', 'MOBILE_APP', 'WEB', 'POS', 'ATM']),
        'ip_address': country_fake.ipv4(),
        'device_id': country_fake.uuid4()[:8]
    }


# Currency symbols for formatting
CURRENCY_SYMBOLS = {
    'INR': '₹', 'USD': '$', 'GBP': '£', 'EUR': '€', 
    'SGD': 'S$', 'AED': 'د.إ', 'AUD': 'A$', 'JPY': '¥'
}


def format_amount(amount, currency='INR'):
    """Format amount with appropriate currency symbol."""
    symbol = CURRENCY_SYMBOLS.get(currency, currency + ' ')
    if currency == 'INR':
        # Indian numbering system
        if amount >= 10000000:
            return f"{symbol}{amount/10000000:.2f} Cr"
        elif amount >= 100000:
            return f"{symbol}{amount/100000:.2f} L"
        elif amount >= 1000:
            return f"{symbol}{amount/1000:.1f}K"
        else:
            return f"{symbol}{amount:,.2f}"
    else:
        # Western numbering system
        if amount >= 1000000:
            return f"{symbol}{amount/1000000:.2f}M"
        elif amount >= 1000:
            return f"{symbol}{amount/1000:.1f}K"
        else:
            return f"{symbol}{amount:,.2f}"


def format_inr(amount):
    """Format amount in Indian numbering system. (Legacy)"""
    return format_amount(amount, 'INR')


def inject_chaos(transaction, chaos_rate=40):
    """
    Takes a clean transaction and decides if it should have issues.
    chaos_rate: % chance of having issues (0-100)
    """
    
    pg_data = transaction.copy()
    cbs_data = transaction.copy()
    mobile_data = transaction.copy()
    
    # Determine if this transaction should have chaos
    if random.randint(1, 100) > chaos_rate:
        return pg_data, cbs_data, mobile_data, "✅ CLEAN (3-WAY MATCH)"
    
    def _weighted_pick(options_with_weights):
        total = float(sum(w for _, w in options_with_weights))
        r = random.random() * total
        upto = 0.0
        for option, weight in options_with_weights:
            upto += float(weight)
            if r <= upto:
                return option
        return options_with_weights[-1][0]

    # Choose chaos type (weighted)
    chaos_type = _weighted_pick(
        [
            ('missing_cbs', 20),
            ('missing_mobile', 15),
            ('amount_mismatch', 20),
            ('status_mismatch', 15),
            ('fraud_attempt', 10),
            ('timestamp_drift', 10),
            ('triple_mismatch', 10),
        ]
    )

    if chaos_type == 'missing_cbs':
        return pg_data, None, mobile_data, "❌ MISSING IN CBS"

    elif chaos_type == 'missing_mobile':
        return pg_data, cbs_data, None, "📱 MISSING IN MOBILE"

    elif chaos_type == 'amount_mismatch':
        cbs_data['amount'] = round(cbs_data['amount'] * random.uniform(0.85, 0.95), 2)
        return pg_data, cbs_data, mobile_data, "⚠️ AMOUNT MISMATCH"

    elif chaos_type == 'status_mismatch':
        pg_data['status'] = 'SUCCESS'
        cbs_data['status'] = random.choice(['PENDING', 'FAILED', 'PROCESSING'])
        mobile_data['status'] = 'SUCCESS'
        return pg_data, cbs_data, mobile_data, "⚠️ STATUS MISMATCH"
        
    elif chaos_type == 'fraud_attempt':
        cbs_data['amount'] = round(cbs_data['amount'] * random.uniform(50, 200), 2)
        return pg_data, cbs_data, mobile_data, "🚨 FRAUD ATTEMPT"

    elif chaos_type == 'timestamp_drift':
        cbs_data['timestamp'] = cbs_data['timestamp'] + random.uniform(10, 120)
        mobile_data['timestamp'] = mobile_data['timestamp'] + random.uniform(5, 60)
        return pg_data, cbs_data, mobile_data, "⏱️ TIMESTAMP DRIFT"

    elif chaos_type == 'triple_mismatch':
        cbs_data['amount'] = round(pg_data['amount'] * random.uniform(0.7, 0.9), 2)
        mobile_data['amount'] = round(pg_data['amount'] * random.uniform(1.1, 1.3), 2)
        return pg_data, cbs_data, mobile_data, "🔥 TRIPLE MISMATCH"

    return pg_data, cbs_data, mobile_data, "UNKNOWN"


print("🚀 Starting Controllable Chaos Generator v3.1 (Resilient Edition)...")
print(f"Targeting Kafka at: {KAFKA_SERVER}")
print(f"📊 Publishing to: {TOPIC_PG}, {TOPIC_CBS}, {TOPIC_MOBILE}")
print(f"🎮 Control via Dashboard or API: /api/chaos/[start|stop|speed]")
print("-" * 60)

# Initialize producer with retries
try:
    producer = create_kafka_producer()
except Exception as e:
    print(f"❌ Could not connect to Kafka. Make sure Kafka is running!")
    print(f"   Run: docker-compose up -d")
    exit(1)

tx_count = 0
chaos_count = 0
last_status_check = 0
cached_status = {"running": True, "speed": 1.0, "chaos_rate": 40}

was_paused = False
consecutive_errors = 0
MAX_CONSECUTIVE_ERRORS = 5

try:
    
    while True:
        current_time = time.time()
        if current_time - last_status_check > POLL_INTERVAL:
            cached_status = get_chaos_status()
            last_status_check = current_time
        
        if not cached_status.get("running", True):
            if not was_paused:
                print()  # New line before pause message
            print("\r⏸️  PAUSED - Use dashboard to resume...    ", end="", flush=True)
            was_paused = True
            time.sleep(0.5)
            continue
        
        if was_paused:
            print()  # New line after resuming
            print("▶️  RESUMED - Generating transactions...")
            was_paused = False
        
        tx_count += 1
        base_txn = generate_transaction()
        
        chaos_rate = cached_status.get("chaos_rate", 40)
        pg_payload, cbs_payload, mobile_payload, log_msg = inject_chaos(base_txn, chaos_rate)
        
        # Apply any active scenario effects (HACKATHON SPECIAL!)
        pg_payload, cbs_payload, mobile_payload, log_msg = apply_scenario_effects(
            base_txn, pg_payload, cbs_payload, mobile_payload, log_msg
        )
        
        try:
            if producer is None:
                logger.error("Producer is None, attempting to reconnect...")
                producer = create_kafka_producer()
            
            # Type guard to ensure producer is not None
            if producer is None:
                logger.error("Failed to create producer, skipping transaction")
                continue
            
            if pg_payload:
                producer.send(TOPIC_PG, pg_payload)
            if cbs_payload:
                producer.send(TOPIC_CBS, cbs_payload)
            if mobile_payload:
                producer.send(TOPIC_MOBILE, mobile_payload)
            producer.flush()
            consecutive_errors = 0  # Reset error counter on success
        except KafkaError as e:
            consecutive_errors += 1
            logger.error(f"[⚠️ KAFKA ERROR] {e} (attempt {consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})")
            
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.warning("🔄 Too many consecutive errors, reconnecting to Kafka...")
                try:
                    if producer is not None:
                        producer.close()
                except:
                    pass
                try:
                    producer = create_kafka_producer()
                    consecutive_errors = 0
                    logger.info("✅ Reconnected to Kafka successfully")
                except Exception as reconnect_error:
                    logger.error(f"❌ Failed to reconnect: {reconnect_error}")
                    time.sleep(5)
            else:
                time.sleep(1)
            continue
        except Exception as e:
            logger.error(f"[⚠️ ERROR] {e}")
            time.sleep(1)
            continue
        
        if "CLEAN" not in log_msg:
            chaos_count += 1
        
        chaos_pct = (chaos_count / tx_count) * 100
        speed = cached_status.get("speed", 1.0)
        
        print(f"[{log_msg}] TXID: {base_txn['transaction_id'][:8]}... | "
              f"{format_inr(base_txn['amount'])} | Speed: {speed}x | Chaos: {chaos_pct:.1f}%")
        
        delay = 1.0 / speed
        time.sleep(delay * random.uniform(0.8, 1.2))

except KeyboardInterrupt:
    print(f"\n🛑 Generator Stopped. Total: {tx_count} txns, {chaos_count} anomalies ({(chaos_count/max(tx_count,1))*100:.1f}% chaos).")
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    if producer is not None:
        try:
            producer.close()
        except:
            pass