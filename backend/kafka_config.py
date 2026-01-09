import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
        return value[1:-1].strip()
    return value


def _try_load_dotenv() -> None:
    """Load environment variables from backend/.env if python-dotenv is available.

    This avoids Windows per-terminal env issues during demos.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    backend_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(backend_dir, ".env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path, override=False)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    value = _strip_wrapping_quotes(value)
    return value if value else default


@dataclass(frozen=True)
class KafkaSettings:
    bootstrap_servers: str
    topics: List[str]
    group_id: str
    security_protocol: Optional[str] = None
    sasl_mechanism: Optional[str] = None
    sasl_plain_username: Optional[str] = None
    sasl_plain_password: Optional[str] = None
    ssl_cafile: Optional[str] = None


def validate_event_hubs_kafka_settings(settings: KafkaSettings) -> Optional[str]:
    """Return a human-friendly error string if SASL settings look invalid.

    This catches the most common misconfigurations for Azure Event Hubs' Kafka endpoint.
    Returns None when settings look plausible.
    """

    if (settings.security_protocol or "").upper() != "SASL_SSL":
        return None
    if (settings.sasl_mechanism or "").upper() != "PLAIN":
        return "KAFKA_SASL_MECHANISM must be PLAIN for Event Hubs Kafka endpoint."

    username = (settings.sasl_plain_username or "").strip()
    password = (settings.sasl_plain_password or "").strip()

    if not username:
        return "KAFKA_SASL_USERNAME is required for SASL_SSL (use $ConnectionString)."
    if username != "$ConnectionString":
        return "KAFKA_SASL_USERNAME must be exactly $ConnectionString for Event Hubs Kafka endpoint."

    if not password:
        return "KAFKA_SASL_PASSWORD is required for SASL_SSL (set it to the Event Hubs connection string)."

    # Detect placeholder values that commonly get left behind.
    lowered = password.lower()
    if "<" in password or ">" in password or "changeme" in lowered or "your_" in lowered:
        return "KAFKA_SASL_PASSWORD looks like a placeholder. Paste the full Event Hubs connection string (Endpoint=sb://...;SharedAccessKeyName=...;SharedAccessKey=...)."

    # Detect common wrong credential type: SAS token instead of connection string.
    if lowered.startswith("sharedaccesssignature") or "sig=" in lowered and "sr=" in lowered:
        return "KAFKA_SASL_PASSWORD appears to be a SAS token. Event Hubs Kafka requires the full connection string, not a SAS token."

    required_parts = ["endpoint=sb://", "sharedaccesskeyname=", "sharedaccesskey="]
    if not all(p in lowered for p in required_parts):
        return (
            "KAFKA_SASL_PASSWORD does not look like an Event Hubs connection string. "
            "Expected: Endpoint=sb://<namespace>.servicebus.windows.net/;SharedAccessKeyName=<name>;SharedAccessKey=<key>[;EntityPath=<eventhub>]"
        )

    return None


def load_kafka_settings() -> KafkaSettings:
    """Load Kafka/Event Hubs settings from environment variables.

    Local Kafka default:
      - KAFKA_BOOTSTRAP_SERVERS=localhost:9092

    Azure Event Hubs (Kafka endpoint) typical:
      - KAFKA_BOOTSTRAP_SERVERS=<namespace>.servicebus.windows.net:9093
      - KAFKA_SECURITY_PROTOCOL=SASL_SSL
      - KAFKA_SASL_MECHANISM=PLAIN
      - KAFKA_SASL_USERNAME=$ConnectionString
      - KAFKA_SASL_PASSWORD=<Event Hubs connection string>
    """

    _try_load_dotenv()

    pg_topic = _env("PG_TOPIC", "pg-transactions") or "pg-transactions"
    cbs_topic = _env("CBS_TOPIC", "cbs-transactions") or "cbs-transactions"
    mobile_topic = _env("MOBILE_TOPIC", "mobile-transactions") or "mobile-transactions"

    return KafkaSettings(
        bootstrap_servers=_env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092") or "localhost:9092",
        topics=[pg_topic, cbs_topic, mobile_topic],
        group_id=_env("KAFKA_GROUP_ID", "banking_reconciler_v3") or "banking_reconciler_v3",
        security_protocol=_env("KAFKA_SECURITY_PROTOCOL"),
        sasl_mechanism=_env("KAFKA_SASL_MECHANISM"),
        sasl_plain_username=_env("KAFKA_SASL_USERNAME"),
        sasl_plain_password=_env("KAFKA_SASL_PASSWORD"),
        ssl_cafile=_env("KAFKA_SSL_CAFILE"),
    )


def build_kafka_common_kwargs(settings: KafkaSettings) -> Dict[str, Any]:
    """Build kwargs for kafka-python clients, supporting SASL_SSL when configured."""
    kwargs: Dict[str, Any] = {
        "bootstrap_servers": settings.bootstrap_servers,
    }

    if settings.security_protocol:
        kwargs["security_protocol"] = settings.security_protocol
    if settings.sasl_mechanism:
        kwargs["sasl_mechanism"] = settings.sasl_mechanism
    if settings.sasl_plain_username:
        kwargs["sasl_plain_username"] = settings.sasl_plain_username
    if settings.sasl_plain_password:
        kwargs["sasl_plain_password"] = settings.sasl_plain_password
    if settings.ssl_cafile:
        kwargs["ssl_cafile"] = settings.ssl_cafile

    return kwargs
