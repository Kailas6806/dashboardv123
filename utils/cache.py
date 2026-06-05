"""Smart TTL cache to prevent duplicate NSE fetches within the same refresh cycle."""
import time
import threading
from config import CACHE_TTL_SECONDS

class TTLCache:
    """Thread-safe cache with per-key time-to-live expiry."""
    
    def __init__(self, default_ttl=None):
        self._store = {}       # key -> (value, expiry_timestamp)
        self._lock = threading.Lock()
        self._default_ttl = default_ttl or CACHE_TTL_SECONDS
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
        self._write_count = 0  # counter for periodic cleanup
    
    def get(self, key):
        """Get value if exists and not expired. Returns None if miss."""
        with self._lock:
            if key in self._store:
                value, expiry = self._store[key]
                if time.time() < expiry:
                    self._stats["hits"] += 1
                    return value
                else:
                    del self._store[key]
                    self._stats["evictions"] += 1
            self._stats["misses"] += 1
            return None
    
    def set(self, key, value, ttl=None):
        """Store value with TTL."""
        ttl = ttl or self._default_ttl
        with self._lock:
            self._store[key] = (value, time.time() + ttl)
            self._write_count += 1
        # Periodic cleanup every 100 writes
        if self._write_count % 100 == 0:
            self.cleanup()
    
    def cleanup(self) -> None:
        """Remove all expired entries from the cache."""
        now = time.time()
        with self._lock:
            expired_keys = [k for k, (_, exp) in self._store.items() if now >= exp]
            for k in expired_keys:
                del self._store[k]
                self._stats["evictions"] += 1
    
    def invalidate(self, key):
        """Force-expire a specific key."""
        with self._lock:
            self._store.pop(key, None)
    
    def clear(self):
        """Clear all entries."""
        with self._lock:
            self._store.clear()
    
    def get_stats(self):
        """Return cache performance stats."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
            return {**self._stats, "hit_rate_pct": round(hit_rate, 1)}
