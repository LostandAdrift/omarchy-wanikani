import subprocess
from . import PLUGIN_ID


class Keyring:
    """Secrets travel over pipes, never argv. No exception includes token text."""
    def get(self, account):
        if not account:
            return None
        try:
            result = subprocess.run(["secret-tool", "lookup", "application", PLUGIN_ID, "account", str(account)], capture_output=True, timeout=8)
            return result.stdout.decode().strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            return None

    def set(self, account, token):
        try:
            result = subprocess.run(["secret-tool", "store", "--label=WaniKani for Omarchy", "application", PLUGIN_ID, "account", str(account)], input=token.encode(), capture_output=True, timeout=30)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def delete(self, account):
        if not account:
            return True
        try:
            result = subprocess.run(["secret-tool", "clear", "application", PLUGIN_ID, "account", str(account)], capture_output=True, timeout=8)
            return result.returncode in (0, 1)
        except (OSError, subprocess.TimeoutExpired):
            return False
