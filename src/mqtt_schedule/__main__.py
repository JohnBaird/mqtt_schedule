from .cli import main
import logging


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        logging.getLogger("mqtt_schedule.cli").critical("application_failed", exc_info=True)
        result = 1
    raise SystemExit(result)
