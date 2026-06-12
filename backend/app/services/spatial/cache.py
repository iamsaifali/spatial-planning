import threading
from collections import OrderedDict
from typing import Generic, TypeVar

T = TypeVar("T")


class LRUCache(Generic[T]):
    def __init__(self, maxsize: int = 256):
        self._data: OrderedDict[str, T] = OrderedDict()
        self._maxsize = max(1, maxsize)
        self._lock = threading.Lock()

    def get(self, key: str) -> T | None:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key: str, value: T) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
