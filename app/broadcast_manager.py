import asyncio
import threading

# === Globale Liste der verbundenen Clients ===
clients = set()
_clients_lock = threading.Lock()


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
