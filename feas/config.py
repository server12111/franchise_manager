import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _safe_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        print(f"[config] WARNING: invalid value for {key}, using default {default}")
        return default


def _safe_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        print(f"[config] WARNING: invalid value for {key}, using default {default}")
        return default


def _safe_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() == "true"


def _parse_admin_ids(raw: str) -> list:
    result = []
    for x in raw.split(","):
        x = x.strip()
        if x:
            try:
                result.append(int(x))
            except ValueError:
                print(f"[config] WARNING: invalid admin id '{x}', skipping")
    return result


@dataclass
class Config:
    BOT_TOKEN: str = ""
    CRYPTOBOT_TOKEN: str = ""
    CRYPTOBOT_TESTNET: bool = False
    ADMIN_IDS: list = field(default_factory=list)
    SUBSCRIPTION_PRICE: float = 3.0
    SUBSCRIPTION_PRICE_7D: float = 1.0
    FREE_ACCOUNTS_LIMIT: int = 10
    EXTRA_ACCOUNT_PRICE: float = 0.2
    SUBSCRIPTION_CURRENCY: str = "USDT"
    PLATEGA_MERCHANT_ID: str = ""
    PLATEGA_SECRET: str = ""
    TON_WALLET_ADDRESS: str = ""
    TONCENTER_API_KEY: str = ""
    TON_SUBSCRIPTION_PRICE: float = 0.5
    TON_EXTRA_ACCOUNT_PRICE: float = 0.05
    PRIVACY_URL: str = "https://telegra.ph/Politika-konfidencialnosti-05-31-36"
    TERMS_URL: str = "https://telegra.ph/Polzovatelskoe-soglashenie-05-31-24"
    DATABASE_PATH: str = "data/bot.db"
    SESSIONS_PATH: str = "sessions"
    MAILING_DEBUG: bool = False
    DEFAULT_API_ID: int = 2040
    DEFAULT_API_HASH: str = "b18441a1ff607e10a989891a5462e627"
    FRANCHISE_OWNER_ID: str = ""
    SUPPORT_USERNAME: str = "autosenderkarta"

    @classmethod
    def from_env(cls) -> "Config":
        admin_raw = os.getenv("ADMIN_IDS", "") or os.getenv("ADMIN_ID", "")
        return cls(
            BOT_TOKEN=os.getenv("FEAS_BOT_TOKEN") or os.getenv("BOT_TOKEN", ""),
            CRYPTOBOT_TOKEN=os.getenv("CRYPTOBOT_TOKEN", ""),
            CRYPTOBOT_TESTNET=_safe_bool("CRYPTOBOT_TESTNET", False),
            ADMIN_IDS=_parse_admin_ids(admin_raw),
            SUBSCRIPTION_PRICE=_safe_float("SUBSCRIPTION_PRICE", 3.0),
            SUBSCRIPTION_PRICE_7D=_safe_float("SUBSCRIPTION_PRICE_7D", 1.0),
            FREE_ACCOUNTS_LIMIT=10,
            EXTRA_ACCOUNT_PRICE=0.2,
            SUBSCRIPTION_CURRENCY=os.getenv("SUBSCRIPTION_CURRENCY", "USDT"),
            PLATEGA_MERCHANT_ID=os.getenv("PLATEGA_MERCHANT_ID", ""),
            PLATEGA_SECRET=os.getenv("PLATEGA_SECRET", ""),
            TON_WALLET_ADDRESS=os.getenv("TON_WALLET_ADDRESS", ""),
            TONCENTER_API_KEY=os.getenv("TONCENTER_API_KEY", ""),
            TON_SUBSCRIPTION_PRICE=_safe_float("TON_SUBSCRIPTION_PRICE", 0.5),
            TON_EXTRA_ACCOUNT_PRICE=_safe_float("TON_EXTRA_ACCOUNT_PRICE", 0.05),
            PRIVACY_URL=os.getenv("PRIVACY_URL", "https://telegra.ph/Politika-konfidencialnosti-05-31-36"),
            TERMS_URL=os.getenv("TERMS_URL", "https://telegra.ph/Polzovatelskoe-soglashenie-05-31-24"),
            DATABASE_PATH=os.getenv("DATABASE_PATH", "data/bot.db"),
            SESSIONS_PATH=os.getenv("SESSIONS_PATH", "sessions"),
            MAILING_DEBUG=_safe_bool("MAILING_DEBUG", False),
            DEFAULT_API_ID=_safe_int("DEFAULT_API_ID", _safe_int("API_ID", 2040)),
            DEFAULT_API_HASH=os.getenv("DEFAULT_API_HASH") or os.getenv("API_HASH", "b18441a1ff607e10a989891a5462e627"),
            FRANCHISE_OWNER_ID=os.getenv("FRANCHISE_OWNER_ID", ""),
            SUPPORT_USERNAME=os.getenv("SUPPORT_USERNAME", "autosenderkarta"),
        )


_real_config: "Config" = Config.from_env()
_config_var: ContextVar["Config"] = ContextVar("_current_config")


class _ConfigProxy:
    __slots__ = ()

    def __getattr__(self, name: str):
        try:
            return getattr(_config_var.get(), name)
        except LookupError:
            return getattr(_real_config, name)

    def __repr__(self):
        try:
            return repr(_config_var.get())
        except LookupError:
            return repr(_real_config)


config: "Config" = _ConfigProxy()  # type: ignore[assignment]
