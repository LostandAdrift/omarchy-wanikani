import subprocess
from . import PLUGIN_ID


class Keyring:
    """Secrets travel over pipes, never argv. No exception includes token text."""
    def __init__(self):
        self.may_have_written = False

    def get(self, account):
        if not account:
            return None
        try:
            result = subprocess.run(["secret-tool", "lookup", "application", PLUGIN_ID, "account", str(account)], capture_output=True, timeout=8)
            return result.stdout.decode().strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            return None

    def set(self, account, token):
        self.may_have_written = False
        try:
            result = subprocess.run(["secret-tool", "store", "--label=WaniKani for Omarchy", "application", PLUGIN_ID, "account", str(account)], input=token.encode(), capture_output=True, timeout=30)
            # A started helper may have stored the token even if its completion
            # failed. A missing executable, in contrast, cannot have written it.
            self.may_have_written = True
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            self.may_have_written = True
            return False
        except OSError:
            return False

    def delete(self, account):
        if not account:
            return True
        try:
            result = subprocess.run(["secret-tool", "clear", "application", PLUGIN_ID, "account", str(account)], capture_output=True, timeout=8)
            return result.returncode in (0, 1)
        except (OSError, subprocess.TimeoutExpired):
            return False
