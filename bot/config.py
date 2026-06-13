import os
from dotenv import load_dotenv

load_dotenv()


def _safe_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    FE_AUTO_SENDER_PATH: str = os.getenv("FE_AUTO_SENDER_PATH", "")
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/manager.db")
    WITHDRAWAL_COMMISSION: float = _safe_float("WITHDRAWAL_COMMISSION", 0.07)
    MIN_SUBSCRIPTION_PRICE: float = _safe_float("MIN_SUBSCRIPTION_PRICE", 3.0)
    SUPPORT_USERNAME: str = "@febashsupportbot"


config = Config()
