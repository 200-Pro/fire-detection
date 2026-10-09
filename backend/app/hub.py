import asyncio
from threading import RLock

class EventHub:
    """Bounded notification fan-out; persisted alerts are the source of truth."""
    def __init__(self):
        self.clients = {}
        self.loop = None
        self.lock = RLock()

    def bind_loop(self, loop):
        self.loop = loop

    def subscribe(self, user_id):
        queue = asyncio.Queue(maxsize=64)
        with self.lock:
            self.clients[queue] = user_id
        return queue

    def remove(self, queue):
        with self.lock:
            self.clients.pop(queue, None)

    def publish(self, user_id, data):
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if self.loop and current_loop is not self.loop:
            self.loop.call_soon_threadsafe(self._publish, user_id, data)
        else:
            self._publish(user_id, data)

    def _publish(self, user_id, data):
        with self.lock:
            clients = list(self.clients.items())
        for queue, owner in clients:
            if owner != user_id:
                continue
            if queue.full():
                queue.get_nowait()  # Client also reconciles persisted events via REST.
            queue.put_nowait(data)
