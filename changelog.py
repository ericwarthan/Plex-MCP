import json
import logging
from datetime import datetime, timezone

from config import CHANGES_LOG

logger = logging.getLogger(__name__)


def log_change(operation: str, item: str, details: str) -> None:
    try:
        CHANGES_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "item": item,
            "details": details,
        }
        with open(CHANGES_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("Failed to write change log: %s", exc)
