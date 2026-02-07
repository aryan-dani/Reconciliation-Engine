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




def load_kafka_settings() -> KafkaSettings:
    """Load Kafka settings from environment variables.

    Local Kafka default:
      - KAFKA_BOOTSTRAP_SERVERS=localhost:9092
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
    """Build kwargs for kafka-python clients, supporting SASL when configured."""
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
