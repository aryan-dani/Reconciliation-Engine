import json
import time
import random
import requests
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable, KafkaError
from faker import Faker
import logging
from kafka_config import build_kafka_common_kwargs, load_kafka_settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

KAFKA_SETTINGS = load_kafka_settings()
KAFKA_SERVER = KAFKA_SETTINGS.bootstrap_servers
TOPIC_PG, TOPIC_CBS, TOPIC_MOBILE = KAFKA_SETTINGS.topics
API_URL = 'http://localhost:5000'

fake = Faker('en_IN')  # Indian locale

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
            return res.json()
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