import aiosqlite
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    balance REAL DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS franchises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    bot_token TEXT UNIQUE NOT NULL,
    bot_username TEXT,
    bot_name TEXT,
    markup_percent REAL DEFAULT 0.0,
    status TEXT DEFAULT 'stopped',
    pid INTEGER,
    instance_dir TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS withdrawal_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    commission REAL NOT NULL,
    net_amount REAL NOT NULL,
    method TEXT NOT NULL,
    wallet TEXT,
    status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    franchise_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    duration_days INTEGER NOT NULL,
    max_uses INTEGER NOT NULL,
    uses_count INTEGER DEFAULT 0,
    cost REAL NOT NULL,
    expires_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (franchise_id) REFERENCES franchises(id)
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    franchise_id INTEGER NOT NULL,
    text TEXT,
    photo_path TEXT,
    video_path TEXT,
    sent INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    blocked INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS franchise_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    franchise_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    channel_username TEXT,
    channel_title TEXT NOT NULL,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(franchise_id, channel_id),
    FOREIGN KEY (franchise_id) REFERENCES franchises(id)
);

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('min_subscription_price', '3.0'),
    ('promo_cost_per_use', '0.5'),
    ('withdrawal_commission', '0.07');
"""


@dataclass
class User:
    id: int
    telegram_id: int
    username: Optional[str]
    balance: float
    created_at: datetime


@dataclass
class Franchise:
    id: int
    user_id: int
    bot_token: str
    bot_username: Optional[str]
    bot_name: Optional[str]
    markup_percent: float
    status: str
    pid: Optional[int]
    instance_dir: Optional[str]
    created_at: datetime

    @property
    def status_emoji(self) -> str:
        return "🟢" if self.status == "running" else "🔴"

    @property
    def display_name(self) -> str:
        return f"@{self.bot_username}" if self.bot_username else self.bot_name or f"Бот #{self.id}"


@dataclass
class Transaction:
    id: int
    user_id: int
    amount: float
    type: str
    description: Optional[str]
    created_at: datetime


@dataclass
class WithdrawalRequest:
    id: int
    user_id: int
    amount: float
    commission: float
    net_amount: float
    method: str
    wallet: Optional[str]
    status: str
    created_at: datetime
    processed_at: Optional[datetime]


@dataclass
class PromoCode:
    id: int
    franchise_id: int
    code: str
    duration_days: int
    max_uses: int
    uses_count: int
    cost: float
    expires_at: Optional[datetime]
    created_at: datetime


@dataclass
class Broadcast:
    id: int
    franchise_id: int
    text: Optional[str]
    photo_path: Optional[str]
    video_path: Optional[str]
    sent: int
    failed: int
    blocked: int
    status: str
    created_at: datetime


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val))
    except Exception:
        return None


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # === Users ===

    async def get_or_create_user(self, telegram_id: int, username: Optional[str] = None) -> User:
        async with self._conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            await self._conn.execute(
                "UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id)
            )
            await self._conn.commit()
            return User(
                id=row["id"], telegram_id=row["telegram_id"], username=username or row["username"],
                balance=row["balance"], created_at=_parse_dt(row["created_at"])
            )
        cur = await self._conn.execute(
            "INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username)
        )
        await self._conn.commit()
        return User(id=cur.lastrowid, telegram_id=telegram_id, username=username,
                    balance=0.0, created_at=datetime.utcnow())

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        async with self._conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return User(id=row["id"], telegram_id=row["telegram_id"], username=row["username"],
                    balance=row["balance"], created_at=_parse_dt(row["created_at"]))

    async def get_user(self, telegram_id: int) -> Optional[User]:
        async with self._conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return User(id=row["id"], telegram_id=row["telegram_id"], username=row["username"],
                    balance=row["balance"], created_at=_parse_dt(row["created_at"]))

    async def get_all_users(self) -> list[User]:
        async with self._conn.execute("SELECT * FROM users ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
        return [User(id=r["id"], telegram_id=r["telegram_id"], username=r["username"],
                     balance=r["balance"], created_at=_parse_dt(r["created_at"])) for r in rows]

    async def update_balance(self, user_id: int, delta: float, tx_type: str, description: str):
        await self._conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?", (delta, user_id)
        )
        await self._conn.execute(
            "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
            (user_id, delta, tx_type, description)
        )
        await self._conn.commit()

    # === Franchises ===

    async def create_franchise(self, user_id: int, bot_token: str, bot_username: str,
                                bot_name: str, instance_dir: str) -> Franchise:
        cur = await self._conn.execute(
            """INSERT INTO franchises (user_id, bot_token, bot_username, bot_name, instance_dir)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, bot_token, bot_username, bot_name, instance_dir)
        )
        await self._conn.commit()
        return Franchise(id=cur.lastrowid, user_id=user_id, bot_token=bot_token,
                         bot_username=bot_username, bot_name=bot_name, markup_percent=0.0,
                         status="stopped", pid=None, instance_dir=instance_dir,
                         created_at=datetime.utcnow())

    async def get_franchise(self, franchise_id: int) -> Optional[Franchise]:
        async with self._conn.execute(
            "SELECT * FROM franchises WHERE id = ?", (franchise_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_franchise(row) if row else None

    async def get_franchise_by_token(self, token: str) -> Optional[Franchise]:
        async with self._conn.execute(
            "SELECT * FROM franchises WHERE bot_token = ?", (token,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_franchise(row) if row else None

    async def get_user_franchises(self, user_id: int) -> list[Franchise]:
        async with self._conn.execute(
            "SELECT * FROM franchises WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_franchise(r) for r in rows]

    async def get_all_franchises(self) -> list[Franchise]:
        async with self._conn.execute(
            "SELECT * FROM franchises ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_franchise(r) for r in rows]

    async def update_franchise_status(self, franchise_id: int, status: str, pid: Optional[int] = None):
        await self._conn.execute(
            "UPDATE franchises SET status = ?, pid = ? WHERE id = ?", (status, pid, franchise_id)
        )
        await self._conn.commit()

    async def update_franchise_markup(self, franchise_id: int, markup_percent: float):
        await self._conn.execute(
            "UPDATE franchises SET markup_percent = ? WHERE id = ?", (markup_percent, franchise_id)
        )
        await self._conn.commit()

    async def delete_franchise(self, franchise_id: int):
        await self._conn.execute("DELETE FROM promo_codes WHERE franchise_id = ?", (franchise_id,))
        await self._conn.execute("DELETE FROM broadcasts WHERE franchise_id = ?", (franchise_id,))
        await self._conn.execute("DELETE FROM franchises WHERE id = ?", (franchise_id,))
        await self._conn.commit()

    def _row_to_franchise(self, row) -> Franchise:
        return Franchise(
            id=row["id"], user_id=row["user_id"], bot_token=row["bot_token"],
            bot_username=row["bot_username"], bot_name=row["bot_name"],
            markup_percent=row["markup_percent"] or 0.0, status=row["status"] or "stopped",
            pid=row["pid"], instance_dir=row["instance_dir"],
            created_at=_parse_dt(row["created_at"])
        )

    # === Settings ===

    async def get_setting(self, key: str, default: str = "") -> str:
        async with self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str):
        await self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        await self._conn.commit()

    async def get_all_settings(self) -> dict:
        async with self._conn.execute("SELECT key, value FROM settings") as cur:
            rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    # === Withdrawals ===

    async def create_withdrawal(self, user_id: int, amount: float, commission: float,
                                 net_amount: float, method: str, wallet: Optional[str]) -> WithdrawalRequest:
        cur = await self._conn.execute(
            """INSERT INTO withdrawal_requests (user_id, amount, commission, net_amount, method, wallet)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, amount, commission, net_amount, method, wallet)
        )
        await self._conn.commit()
        return WithdrawalRequest(id=cur.lastrowid, user_id=user_id, amount=amount,
                                  commission=commission, net_amount=net_amount,
                                  method=method, wallet=wallet, status="pending",
                                  created_at=datetime.utcnow(), processed_at=None)

    async def get_withdrawal(self, request_id: int) -> Optional[WithdrawalRequest]:
        async with self._conn.execute(
            "SELECT * FROM withdrawal_requests WHERE id = ?", (request_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_withdrawal(row) if row else None

    async def get_pending_withdrawals(self) -> list[WithdrawalRequest]:
        async with self._conn.execute(
            "SELECT * FROM withdrawal_requests WHERE status = 'pending' ORDER BY created_at"
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_withdrawal(r) for r in rows]

    async def process_withdrawal(self, request_id: int, status: str):
        await self._conn.execute(
            "UPDATE withdrawal_requests SET status = ?, processed_at = ? WHERE id = ?",
            (status, datetime.utcnow().isoformat(), request_id)
        )
        await self._conn.commit()

    async def get_user_withdrawals(self, user_id: int) -> list[WithdrawalRequest]:
        async with self._conn.execute(
            "SELECT * FROM withdrawal_requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_withdrawal(r) for r in rows]

    def _row_to_withdrawal(self, row) -> WithdrawalRequest:
        return WithdrawalRequest(
            id=row["id"], user_id=row["user_id"], amount=row["amount"],
            commission=row["commission"], net_amount=row["net_amount"],
            method=row["method"], wallet=row["wallet"], status=row["status"],
            created_at=_parse_dt(row["created_at"]), processed_at=_parse_dt(row["processed_at"])
        )

    # === Promo Codes ===

    async def create_promo(self, franchise_id: int, code: str, duration_days: int,
                            max_uses: int, cost: float, expires_at: Optional[datetime]) -> PromoCode:
        cur = await self._conn.execute(
            """INSERT INTO promo_codes (franchise_id, code, duration_days, max_uses, cost, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (franchise_id, code, duration_days, max_uses, cost,
             expires_at.isoformat() if expires_at else None)
        )
        await self._conn.commit()
        return PromoCode(id=cur.lastrowid, franchise_id=franchise_id, code=code,
                         duration_days=duration_days, max_uses=max_uses, uses_count=0,
                         cost=cost, expires_at=expires_at, created_at=datetime.utcnow())

    async def get_franchise_promos(self, franchise_id: int) -> list[PromoCode]:
        async with self._conn.execute(
            "SELECT * FROM promo_codes WHERE franchise_id = ? ORDER BY created_at DESC",
            (franchise_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_promo(r) for r in rows]

    async def get_promo_by_id(self, promo_id: int) -> Optional[dict]:
        async with self._conn.execute(
            "SELECT * FROM promo_codes WHERE id = ?", (promo_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_promo(self, promo_id: int):
        await self._conn.execute("DELETE FROM promo_codes WHERE id = ?", (promo_id,))
        await self._conn.commit()

    def _row_to_promo(self, row) -> PromoCode:
        return PromoCode(
            id=row["id"], franchise_id=row["franchise_id"], code=row["code"],
            duration_days=row["duration_days"], max_uses=row["max_uses"],
            uses_count=row["uses_count"], cost=row["cost"],
            expires_at=_parse_dt(row["expires_at"]), created_at=_parse_dt(row["created_at"])
        )

    # === Transactions ===

    async def get_user_transactions(self, user_id: int, limit: int = 15) -> list[Transaction]:
        async with self._conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
        return [Transaction(id=r["id"], user_id=r["user_id"], amount=r["amount"],
                            type=r["type"], description=r["description"],
                            created_at=_parse_dt(r["created_at"])) for r in rows]

    # === Broadcasts ===

    async def create_broadcast(self, franchise_id: int, text: Optional[str],
                                photo_path: Optional[str] = None,
                                video_path: Optional[str] = None) -> Broadcast:
        cur = await self._conn.execute(
            """INSERT INTO broadcasts (franchise_id, text, photo_path, video_path)
               VALUES (?, ?, ?, ?)""",
            (franchise_id, text, photo_path, video_path)
        )
        await self._conn.commit()
        return Broadcast(id=cur.lastrowid, franchise_id=franchise_id, text=text,
                         photo_path=photo_path, video_path=video_path,
                         sent=0, failed=0, blocked=0, status="pending",
                         created_at=datetime.utcnow())

    async def get_broadcast_by_id(self, broadcast_id: int) -> Optional[dict]:
        async with self._conn.execute(
            "SELECT * FROM broadcasts WHERE id = ?", (broadcast_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def update_broadcast_stats(self, broadcast_id: int, sent: int, failed: int, blocked: int):
        await self._conn.execute(
            "UPDATE broadcasts SET sent = ?, failed = ?, blocked = ?, status = 'done' WHERE id = ?",
            (sent, failed, blocked, broadcast_id)
        )
        await self._conn.commit()

    # === Franchise Channels ===

    async def get_franchise_channels(self, franchise_id: int) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM franchise_channels WHERE franchise_id = ? ORDER BY added_at",
            (franchise_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_franchise_channels(self, franchise_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM franchise_channels WHERE franchise_id = ?", (franchise_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def add_franchise_channel(self, franchise_id: int, channel_id: int,
                                     channel_username: Optional[str], channel_title: str):
        await self._conn.execute(
            """INSERT OR REPLACE INTO franchise_channels
               (franchise_id, channel_id, channel_username, channel_title)
               VALUES (?, ?, ?, ?)""",
            (franchise_id, channel_id, channel_username, channel_title)
        )
        await self._conn.commit()

    async def remove_franchise_channel(self, franchise_id: int, channel_id: int):
        await self._conn.execute(
            "DELETE FROM franchise_channels WHERE franchise_id = ? AND channel_id = ?",
            (franchise_id, channel_id)
        )
        await self._conn.commit()
