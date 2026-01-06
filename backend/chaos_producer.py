import json
import time
import random
import requests
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable, KafkaError
from faker import Faker
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

KAFKA_SERVER = 'localhost:9092'
TOPIC_PG = 'pg-transactions'
TOPIC_CBS = 'cbs-transactions'
TOPIC_MOBILE = 'mobile-transactions'
API_URL = 'http://localhost:5000'

fake = Faker('en_IN')  # Indian locale

def create_kafka_producer(max_retries=10, retry_delay=3):
    """Create Kafka producer with retry logic."""
    for attempt in range(max_retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_SERVER,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                retries=5,
                retry_backoff_ms=1000,
                request_timeout_ms=30000,
                max_block_ms=60000
            )
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

# Indian Banks and UPI
INDIAN_BANKS = ['HDFC', 'ICICI', 'SBI', 'AXIS', 'KOTAK', 'PNB', 'BOB', 'IDBI', 'YES', 'CANARA']
UPI_HANDLES = ['@ybl', '@paytm', '@okaxis', '@oksbi', '@okicici', '@apl', '@ibl']

# Transaction categories
TRANSACTION_TYPES = ['UPI_TRANSFER', 'NEFT', 'IMPS', 'RTGS', 'CARD_PAYMENT', 'WALLET', 'EMI', 'BILL_PAYMENT']
MERCHANT_CATEGORIES = ['RETAIL', 'FOOD', 'TRAVEL', 'UTILITIES', 'ENTERTAINMENT', 'HEALTHCARE', 'EDUCATION', 'E-COMMERCE']
INDIAN_CITIES = ['Mumbai', 'Delhi', 'Bangalore', 'Chennai', 'Kolkata', 'Hyderabad', 'Pune', 'Ahmedabad', 'Jaipur', 'Lucknow']

POLL_INTERVAL = 5

def get_chaos_status():
    try:
        res = requests.get(f'{API_URL}/api/chaos/status', timeout=1)
        if res.status_code == 200:
            return res.json()
    except requests.exceptions.RequestException:
        pass
    return {"running": True, "speed": 1.0, "chaos_rate": 40}


def generate_transaction():
    """Creates a base legitimate Indian transaction."""
    upi_id = f"{fake.first_name().lower()}{random.randint(1, 999)}{random.choice(UPI_HANDLES)}"
    
    return {
        'transaction_id': fake.uuid4(),
        'user_id': f"ACC{random.randint(10000000, 99999999)}",
        'upi_id': upi_id,
        'amount': round(random.uniform(100.00, 500000.00), 2),
        'currency': 'INR',
        'country': 'IN',
        'city': random.choice(INDIAN_CITIES),
        'bank': random.choice(INDIAN_BANKS),
        'timestamp': time.time(),
        'status': 'SUCCESS',
        'type': random.choice(TRANSACTION_TYPES),
        'merchant_category': random.choice(MERCHANT_CATEGORIES),
        'channel': random.choice(['UPI', 'NETBANKING', 'MOBILE_APP', 'POS', 'ATM']),
        'ip_address': fake.ipv4(),
        'device_id': fake.uuid4()[:8]
    }


def format_inr(amount):
    """Format amount in Indian numbering system."""
    if amount >= 10000000:
        return f"₹{amount/10000000:.2f} Cr"
    elif amount >= 100000:
        return f"₹{amount/100000:.2f} L"
    elif amount >= 1000:
        return f"₹{amount/1000:.1f}K"
    else:
        return f"₹{amount:,.2f}"

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
    
    # Choose chaos type
    chaos_type = random.choices(
        ['missing_cbs', 'missing_mobile', 'amount_mismatch', 
         'status_mismatch', 'fraud_attempt', 'timestamp_drift', 'triple_mismatch'],
        weights=[20, 15, 20, 15, 10, 10, 10]
    )[0]

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