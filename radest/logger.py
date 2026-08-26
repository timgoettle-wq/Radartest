import logging
import sys
from datetime import datetime
from pathlib import Path


LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

log_file = LOG_DIR / (
    "RadestSoftware_"
    + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    + ".txt"
)

logging.basicConfig(
    filename=log_file,
    format="%(asctime)s:%(levelname)s:%(message)s",
    level=logging.WARNING
)

globalLogger = logging.getLogger()
globalLogger.addHandler(
    logging.StreamHandler(sys.stdout)
)