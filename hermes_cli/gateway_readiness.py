"""Wait for the old gateway listener to release its address before restarting."""
import socket
import sys
import time


def wait_for_tcp_port_free(host: str, port: int, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sys.platform == "win32":
            from hermes_cli.web_server_lifecycle import _port_bind_conflict
            # A Windows firewall can time out closed-port SYNs; probe the exclusive bind instead.
            if not _port_bind_conflict(host, port):
                return True
        else:
            try:
                with socket.create_connection((host, port), timeout=0.2):
                    pass
            except ConnectionRefusedError:
                return True
            except TimeoutError:
                pass  # A slow accept queue is still a live listener.
            except OSError:
                return True  # The actual bind reports invalid or unreachable addresses.
        time.sleep(0.1)
    return False
