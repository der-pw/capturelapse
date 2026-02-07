import asyncio
import threading
from typing import Optional

# === Globale Liste der verbundenen Clients ===
clients = set()
_clients_lock = threading.Lock()
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the main asyncio loop for thread-safe broadcasts."""
    global _main_loop
    _main_loop = loop


def add_client(client) -> None:
    with _clients_lock:
        clients.add(client)


def remove_client(client) -> None:
    with _clients_lock:
        clients.discard(client)


def _snapshot_clients():
    with _clients_lock:
        return list(clients)


async def broadcast(message: dict):
    """Sendet Nachricht an alle verbundenen SSE-Clients."""
    dead = []
    for client in _snapshot_clients():
        try:
            await client.put(message)
        except Exception:
            dead.append(client)
    if dead:
        with _clients_lock:
            for d in dead:
                clients.discard(d)


def broadcast_threadsafe(message: dict) -> None:
    """Schedule a broadcast on the main loop from any thread."""
    loop = _main_loop
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(message), loop)
        return
    # Fallback: best-effort direct run (mainly for tests).
    try:
        asyncio.run(broadcast(message))
    except RuntimeError:
        # If no loop can be started, silently drop (avoids crashing scheduler threads).
        pass
