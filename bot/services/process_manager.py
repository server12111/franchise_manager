import os
import sys
import signal
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ProcessManager:
    def __init__(self, fe_path: str):
        self.fe_path = fe_path
        self._procs: dict[int, subprocess.Popen] = {}

    def start(self, franchise_id: int, token: str, instance_dir: str,
              owner_id: int, price: float, markup: float = 0.0) -> bool:
        if not self.fe_path or not os.path.isdir(self.fe_path):
            logger.error(f"feAutoSender path not found: {self.fe_path}")
            return False

        self.stop(franchise_id, self._get_stored_pid(franchise_id))

        abs_instance = os.path.abspath(instance_dir)
        db_path = os.path.join(abs_instance, "data", "bot.db")
        sessions_path = os.path.join(abs_instance, "sessions")

        env = os.environ.copy()
        env.update({
            "BOT_TOKEN": token,
            "ADMIN_IDS": str(owner_id),
            "DATABASE_PATH": db_path,
            "SESSIONS_PATH": sessions_path,
            "SUBSCRIPTION_PRICE": f"{price:.2f}",
            "FRANCHISE_OWNER_ID": str(owner_id),
            "SUPPORT_USERNAME": "febashsupportbot",
        })

        env_file = os.path.join(abs_instance, ".env")
        if os.path.exists(env_file):
            _load_env_file(env_file, env)

        try:
            log_file = open(os.path.join(abs_instance, "bot.log"), "a", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, "-m", "bot.main"],
                cwd=self.fe_path,
                env=env,
                stdout=log_file,
                stderr=log_file,
            )
            log_file.close()
            self._procs[franchise_id] = proc
            logger.info(f"Started franchise {franchise_id}, PID {proc.pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to start franchise {franchise_id}: {e}")
            return False

    def stop(self, franchise_id: int, pid: Optional[int] = None):
        proc = self._procs.pop(franchise_id, None)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            logger.info(f"Stopped franchise {franchise_id}")
            return

        if pid:
            try:
                if sys.platform == "win32":
                    subprocess.call(["taskkill", "/F", "/PID", str(pid)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    os.kill(pid, signal.SIGTERM)
                logger.info(f"Killed PID {pid} (franchise {franchise_id})")
            except Exception as e:
                logger.debug(f"Could not kill PID {pid}: {e}")

    def get_pid(self, franchise_id: int) -> Optional[int]:
        proc = self._procs.get(franchise_id)
        return proc.pid if proc else None

    def is_running(self, franchise_id: int) -> bool:
        proc = self._procs.get(franchise_id)
        if not proc:
            return False
        return proc.poll() is None

    def check_and_cleanup(self) -> list[int]:
        """Returns list of franchise_ids whose process has died unexpectedly."""
        dead = []
        for fid, proc in list(self._procs.items()):
            if proc.poll() is not None:
                dead.append(fid)
                del self._procs[fid]
                logger.warning(f"Franchise {fid} process died (exit code {proc.returncode})")
        return dead

    def _get_stored_pid(self, franchise_id: int) -> Optional[int]:
        proc = self._procs.get(franchise_id)
        return proc.pid if proc else None

    def restore_running(self, franchises: list) -> None:
        for f in franchises:
            if f.status == "running" and f.instance_dir:
                # Читаем реальную цену из .env экземпляра
                price = _read_price_from_env(f.instance_dir)
                owner_id = _read_owner_from_env(f.instance_dir)
                self.start(f.id, f.bot_token, f.instance_dir, owner_id, price, f.markup_percent)
                logger.info(f"Restored franchise {f.id} ({f.display_name}), price={price}")


def _load_env_file(path: str, env: dict):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def _read_price_from_env(instance_dir: str) -> float:
    env_path = os.path.join(instance_dir, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("SUBSCRIPTION_PRICE="):
                    return float(line.split("=", 1)[1])
    except Exception:
        pass
    return 3.0


def _read_owner_from_env(instance_dir: str) -> int:
    env_path = os.path.join(instance_dir, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("FRANCHISE_OWNER_ID="):
                    return int(line.split("=", 1)[1])
    except Exception:
        pass
    return 0
