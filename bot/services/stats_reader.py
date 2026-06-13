import os
import aiosqlite


class StatsReader:
    @staticmethod
    async def read(instance_dir: str) -> dict:
        default = {
            "users_total": 0,
            "users_blocked": 0,
            "subscribers_active": 0,
            "revenue_total": 0.0,
            "accounts_count": 0,
            "mailings_active": 0,
        }
        if not instance_dir:
            return default

        db_path = os.path.join(instance_dir, "data", "bot.db")
        if not os.path.exists(db_path):
            return default

        try:
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row

                async with conn.execute("SELECT COUNT(*) as c FROM users") as cur:
                    row = await cur.fetchone()
                    default["users_total"] = row["c"] if row else 0

                try:
                    async with conn.execute(
                        "SELECT COUNT(*) as c FROM users WHERE subscription_end IS NOT NULL "
                        "AND subscription_end > datetime('now')"
                    ) as cur:
                        row = await cur.fetchone()
                        default["subscribers_active"] = row["c"] if row else 0
                except Exception:
                    pass

                try:
                    async with conn.execute(
                        "SELECT COUNT(*) as c FROM payments WHERE status = 'paid'"
                    ) as cur:
                        row = await cur.fetchone()
                        pass
                    async with conn.execute(
                        "SELECT COALESCE(SUM(amount), 0) as s FROM payments WHERE status = 'paid'"
                    ) as cur:
                        row = await cur.fetchone()
                        default["revenue_total"] = float(row["s"]) if row else 0.0
                except Exception:
                    pass

                try:
                    async with conn.execute("SELECT COUNT(*) as c FROM accounts") as cur:
                        row = await cur.fetchone()
                        default["accounts_count"] = row["c"] if row else 0
                except Exception:
                    pass

                try:
                    async with conn.execute(
                        "SELECT COUNT(*) as c FROM mailings WHERE is_active = 1"
                    ) as cur:
                        row = await cur.fetchone()
                        default["mailings_active"] = row["c"] if row else 0
                except Exception:
                    pass

        except Exception:
            pass

        return default
