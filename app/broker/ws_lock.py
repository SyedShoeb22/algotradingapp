"""Shared Linux process-level lock for Angel One WebSocket connections.

Ensures mutual exclusion across multiple processes and projects:
- algotradingapp
- nse_trading_app

Angel One permits only ONE active WebSocket connection per API key/client account.
Simultaneous connections result in HTTP 429: Connection Limit Exceeded.
This lock uses kernel-level fcntl.flock to guarantee mutual exclusion.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import stat
from types import TracebackType
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_LOCK_DIR = "/home/ubuntu/.algotrading_locks"
DEFAULT_LOCK_PATH = "/home/ubuntu/.algotrading_locks/angel_one_ws.lock"


class AngelOneWebSocketLock:
    """Non-blocking exclusive cross-process lock using fcntl.flock.
    
    Guarantees:
    - Fails closed if the lock directory is missing, cannot be created,
      or has insecure permissions (e.g. world-writable).
    - Never unlinks the lock file to avoid inode split-locking.
    - Automatic kernel cleanup on abnormal process termination.
    """

    def __init__(self, lock_path: str = DEFAULT_LOCK_PATH):
        self.lock_path = lock_path
        self._fd: Optional[int] = None
        self._acquired = False

    @property
    def is_acquired(self) -> bool:
        return self._acquired

    def _ensure_secure_dir(self) -> bool:
        """Verify or create lock directory with restrictive permissions.
        
        Returns False on any security issue (fails closed without fallback).
        """
        lock_dir = os.path.dirname(os.path.abspath(self.lock_path))
        try:
            if not os.path.exists(lock_dir):
                os.makedirs(lock_dir, mode=0o700, exist_ok=True)

            dir_stat = os.stat(lock_dir)

            # Insecure directory check: reject if world-writable
            if (dir_stat.st_mode & stat.S_IWOTH) != 0:
                logger.error(
                    "Insecure lock directory %s is world-writable (mode %o). Aborting.",
                    lock_dir,
                    dir_stat.st_mode,
                )
                return False

            return True

        except Exception as exc:
            logger.error(
                "Failed to verify or create secure lock directory %s: %s",
                lock_dir,
                exc,
            )
            return False

    def acquire(self) -> bool:
        """Attempt to acquire the exclusive lock without blocking.

        Returns:
            True if acquired, False if held by another process or directory insecure.
        """
        if self._acquired:
            return True

        # Security check: fail closed if directory cannot be secured
        if not self._ensure_secure_dir():
            return False

        try:
            # Open file for read/write, creating it if it does not exist (mode 0600)
            self._fd = os.open(
                self.lock_path,
                os.O_CREAT | os.O_RDWR,
                0o600,
            )
            # Try non-blocking exclusive lock
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._acquired = True

            # Write owner PID into the file for diagnostic visibility
            try:
                os.ftruncate(self._fd, 0)
                os.lseek(self._fd, 0, os.SEEK_SET)
                os.write(self._fd, f"PID={os.getpid()}\n".encode())
            except Exception:
                pass

            logger.info(
                "Acquired Angel One WebSocket lock on %s (PID=%s)",
                self.lock_path,
                os.getpid(),
            )
            return True

        except (BlockingIOError, OSError) as exc:
            # Errno 11: EAGAIN / EWOULDBLOCK means lock is held by another process
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                logger.warning(
                    "Angel One WebSocket lock on %s is held by another process. "
                    "Connection aborted to prevent HTTP 429 connection limit lockout.",
                    self.lock_path,
                )
                self._cleanup_fd()
                self._acquired = False
                return False

            logger.error(
                "Unexpected error acquiring WebSocket lock on %s: %s",
                self.lock_path,
                exc,
            )
            self._cleanup_fd()
            self._acquired = False
            return False

    def release(self) -> None:
        """Release the lock and close file descriptor.

        Does NOT delete the lock file so that existing file descriptors
        in other processes remain valid and references remain stable.
        """
        if not self._acquired or self._fd is None:
            self._cleanup_fd()
            return

        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            logger.info(
                "Released Angel One WebSocket lock on %s (PID=%s)",
                self.lock_path,
                os.getpid(),
            )
        except Exception as exc:
            logger.warning("Error releasing WebSocket lock: %s", exc)
        finally:
            self._cleanup_fd()
            self._acquired = False

    def _cleanup_fd(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.release()
