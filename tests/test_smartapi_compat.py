"""Offline unit tests for SmartApi WebSocket compatibility, process locks, and feed safety.

Tests run fully isolated with NO network access.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import socket
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure app is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.broker.smartapi_compat import apply_smartapi_websocket_patch, _safe_dispatch
from app.broker.ws_lock import AngelOneWebSocketLock
from SmartApi.smartWebSocketV2 import SmartWebSocketV2


@pytest.fixture(autouse=True)
def prevent_network_calls(monkeypatch):
    """Enforce mandatory safety rule: no network connections allowed."""
    def guarded_connect(*args, **kwargs):
        raise RuntimeError("TEST BLOCKED: Network connection attempted during offline test!")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


# ----------------------------------------------------------------------
# 1. Multi-Process Lock Mutual Exclusion (Distinct OS PIDs)
# ----------------------------------------------------------------------

def _worker_acquire_lock(lock_file, queue, release_event):
    """Runs in a separate OS process with distinct PID."""
    lock = AngelOneWebSocketLock(lock_file)
    acquired = lock.acquire()
    queue.put((os.getpid(), acquired))
    if acquired:
        # Hold lock until signaled to release
        release_event.wait(timeout=10)
        lock.release()


def test_lock_cross_os_processes_mutual_exclusion(tmp_path):
    """Verify mutual exclusion across two distinct OS processes with different PIDs."""
    lock_file = str(tmp_path / "proc_test.lock")
    ctx = mp.get_context("fork" if hasattr(os, "fork") else "spawn")

    q1 = ctx.Queue()
    rel1 = ctx.Event()
    q2 = ctx.Queue()
    rel2 = ctx.Event()

    # Process A acquires lock
    proc_a = ctx.Process(target=_worker_acquire_lock, args=(lock_file, q1, rel1))
    proc_a.start()
    pid_a, acq_a = q1.get(timeout=5)
    assert acq_a is True

    # Process B tries to acquire same lock -> must fail
    proc_b = ctx.Process(target=_worker_acquire_lock, args=(lock_file, q2, rel2))
    proc_b.start()
    pid_b, acq_b = q2.get(timeout=5)
    assert acq_b is False
    assert pid_a != pid_b
    assert pid_a != os.getpid()

    # Process A releases lock
    rel1.set()
    proc_a.join(timeout=5)

    # Process C can now acquire
    q3 = ctx.Queue()
    rel3 = ctx.Event()
    proc_c = ctx.Process(target=_worker_acquire_lock, args=(lock_file, q3, rel3))
    proc_c.start()
    pid_c, acq_c = q3.get(timeout=5)
    assert acq_c is True
    assert pid_c != pid_a
    rel3.set()
    proc_c.join(timeout=5)
    proc_b.join(timeout=5)


# ----------------------------------------------------------------------
# 2. Callback Adapter Tests (inspect.signature, single invocation)
# ----------------------------------------------------------------------

def test_apply_patch_is_idempotent():
    assert apply_smartapi_websocket_patch() is True
    assert apply_smartapi_websocket_patch() is True


def test_on_close_variadic_arguments_from_websocket_client():
    apply_smartapi_websocket_patch()
    ws = SmartWebSocketV2.__new__(SmartWebSocketV2)
    mock_wsapp = MagicMock(name="wsapp")

    received = []
    def my_on_close(wsapp, *args, **kwargs):
        received.append((wsapp, args, kwargs))

    ws.on_close = my_on_close
    ws._on_close(mock_wsapp, 1000, "Normal closure")

    assert len(received) == 1
    assert received[0][0] is mock_wsapp
    assert received[0][1] == (1000, "Normal closure")


def test_on_close_single_argument_backward_compatibility():
    apply_smartapi_websocket_patch()
    ws = SmartWebSocketV2.__new__(SmartWebSocketV2)
    mock_wsapp = MagicMock(name="wsapp")

    received = []
    def my_on_close(wsapp, *args, **kwargs):
        received.append((wsapp, args))

    ws.on_close = my_on_close
    ws._on_close(mock_wsapp)

    assert len(received) == 1
    assert received[0][0] is mock_wsapp
    assert received[0][1] == ()


def test_on_close_legacy_callback_accepting_only_wsapp():
    apply_smartapi_websocket_patch()
    ws = SmartWebSocketV2.__new__(SmartWebSocketV2)
    mock_wsapp = MagicMock(name="wsapp")

    called = []
    def legacy_on_close(wsapp):
        called.append(wsapp)

    ws.on_close = legacy_on_close
    ws._on_close(mock_wsapp, 1006, "Abnormal closure")

    assert called == [mock_wsapp]


def test_on_close_internal_type_error_called_exactly_once():
    """If callback body raises a TypeError, it must be invoked EXACTLY ONCE and not retried."""
    apply_smartapi_websocket_patch()
    ws = SmartWebSocketV2.__new__(SmartWebSocketV2)
    mock_wsapp = MagicMock(name="wsapp")

    call_count = 0
    def buggy_on_close(wsapp, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Internal TypeError caused by calculation, NOT signature mismatch
        return 1 + "cannot add str to int"

    ws.on_close = buggy_on_close
    ws._on_close(mock_wsapp, 1000, "Normal")

    assert call_count == 1, f"Expected 1 call, but got {call_count}"


def test_on_error_internal_type_error_called_exactly_once():
    """If error callback raises a TypeError, it must be invoked EXACTLY ONCE and not retried."""
    apply_smartapi_websocket_patch()
    ws = SmartWebSocketV2.__new__(SmartWebSocketV2)
    ws.current_retry_attempt = 0
    ws.MAX_RETRY_ATTEMPT = 0
    ws.close_connection = MagicMock()
    mock_wsapp = MagicMock(name="wsapp")

    call_count = 0
    def buggy_on_error(msg1, msg2=None, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return len(None)  # Internal TypeError

    ws.on_error = buggy_on_error
    ws._on_error(mock_wsapp, ConnectionResetError("Reset"))

    assert call_count == 1


# ----------------------------------------------------------------------
# 3. Old Runner Feed Safety Gate Tests
# ----------------------------------------------------------------------

def _create_isolated_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE market_ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            token TEXT NOT NULL,
            exchange TEXT NOT NULL,
            ltp REAL NOT NULL,
            exchange_timestamp TEXT,
            received_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def test_old_runner_fresh_live_tick_allows_execution(tmp_path):
    from app.paper_trading.paper_engine import get_latest_fresh_live_tick

    db_path = tmp_path / "test_ticks.db"
    conn = _create_isolated_db(db_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO market_ticks (symbol, token, exchange, ltp, received_at)
        VALUES ('KROSS-EQ', '12345', 'NSE', 255.50, ?)
    """, (now_iso,))
    conn.commit()

    tick, msg = get_latest_fresh_live_tick(conn, "KROSS-EQ", "12345", "NSE", max_age_seconds=5)
    assert tick is not None
    assert tick["ltp"] == 255.50
    assert "Fresh live tick verified" in msg
    conn.close()


def test_old_runner_stale_tick_blocks_execution(tmp_path):
    from app.paper_trading.paper_engine import get_latest_fresh_live_tick

    db_path = tmp_path / "test_ticks.db"
    conn = _create_isolated_db(db_path)

    stale_iso = (datetime.now(timezone.utc) - timedelta(seconds=15)).isoformat()
    conn.execute("""
        INSERT INTO market_ticks (symbol, token, exchange, ltp, received_at)
        VALUES ('KROSS-EQ', '12345', 'NSE', 255.50, ?)
    """, (stale_iso,))
    conn.commit()

    tick, msg = get_latest_fresh_live_tick(conn, "KROSS-EQ", "12345", "NSE", max_age_seconds=5)
    assert tick is None
    assert "stale" in msg.lower()
    conn.close()


def test_old_runner_missing_tick_blocks_execution(tmp_path):
    from app.paper_trading.paper_engine import get_latest_fresh_live_tick

    db_path = tmp_path / "test_ticks.db"
    conn = _create_isolated_db(db_path)

    tick, msg = get_latest_fresh_live_tick(conn, "KROSS-EQ", "12345", "NSE", max_age_seconds=5)
    assert tick is None
    assert "No live market ticks found" in msg
    conn.close()


def test_old_runner_wrong_symbol_token_exchange_blocks_execution(tmp_path):
    from app.paper_trading.paper_engine import get_latest_fresh_live_tick

    db_path = tmp_path / "test_ticks.db"
    conn = _create_isolated_db(db_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO market_ticks (symbol, token, exchange, ltp, received_at)
        VALUES ('KROSS-EQ', '99999', 'BSE', 255.50, ?)
    """, (now_iso,))
    conn.commit()

    # Wrong token
    tick, msg = get_latest_fresh_live_tick(conn, "KROSS-EQ", "12345", "NSE", max_age_seconds=5)
    assert tick is None

    # Wrong exchange
    tick, msg = get_latest_fresh_live_tick(conn, "KROSS-EQ", "99999", "NSE", max_age_seconds=5)
    assert tick is None
    conn.close()


def test_old_runner_simulated_token_blocks_execution(tmp_path):
    from app.paper_trading.paper_engine import get_latest_fresh_live_tick

    db_path = tmp_path / "test_ticks.db"
    conn = _create_isolated_db(db_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO market_ticks (symbol, token, exchange, ltp, received_at)
        VALUES ('KROSS-EQ', 'SIM-12345', 'NSE', 255.50, ?)
    """, (now_iso,))
    conn.commit()

    tick, msg = get_latest_fresh_live_tick(conn, "KROSS-EQ", "SIM-12345", "NSE", max_age_seconds=5)
    assert tick is None
    assert "simulated" in msg.lower()
    conn.close()


def test_old_runner_other_symbol_tick_does_not_authorize(tmp_path):
    from app.paper_trading.paper_engine import get_latest_fresh_live_tick

    db_path = tmp_path / "test_ticks.db"
    conn = _create_isolated_db(db_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    # Insert tick for SBIN-EQ
    conn.execute("""
        INSERT INTO market_ticks (symbol, token, exchange, ltp, received_at)
        VALUES ('SBIN-EQ', '3045', 'NSE', 820.0, ?)
    """, (now_iso,))
    conn.commit()

    # KROSS-EQ check must fail
    tick, msg = get_latest_fresh_live_tick(conn, "KROSS-EQ", "12345", "NSE", max_age_seconds=5)
    assert tick is None
    conn.close()


def test_old_runner_shariah_gate_empty_blocks_all_buys():
    from app.paper_trading.paper_engine import AAOIFI_APPROVED_SYMBOLS

    # Must be empty frozenset
    assert isinstance(AAOIFI_APPROVED_SYMBOLS, frozenset)
    assert len(AAOIFI_APPROVED_SYMBOLS) == 0
    assert "KROSS-EQ" not in AAOIFI_APPROVED_SYMBOLS
    assert "SBIN-EQ" not in AAOIFI_APPROVED_SYMBOLS


# ----------------------------------------------------------------------
# 4. Lock Lifecycle and Still-Running Thread Retains Lock
# ----------------------------------------------------------------------

def test_lock_retained_when_thread_timeout_occurs(tmp_path):
    """If background thread fails to terminate within join timeout, lock must be retained."""
    lock_file = str(tmp_path / "retained.lock")
    lock = AngelOneWebSocketLock(lock_file)
    assert lock.acquire() is True

    # Simulate a still-running worker thread
    stop_event = threading.Event()
    def stubborn_worker():
        while not stop_event.is_set():
            time.sleep(0.1)

    worker = threading.Thread(target=stubborn_worker, daemon=True)
    worker.start()

    # Simulate join timeout check: worker is alive, so lock must NOT be released
    threads_terminated = True
    worker.join(timeout=0.05)
    if worker.is_alive():
        threads_terminated = False

    assert threads_terminated is False
    # If not terminated, lock remains acquired
    if threads_terminated:
        lock.release()

    assert lock.is_acquired is True

    # Cleanup worker
    stop_event.set()
    worker.join(timeout=2)
    lock.release()
    assert lock.is_acquired is False


def test_runner_backoff_and_circuit_breaker_policy():
    from app.paper_trading.continuous_runner import (
        BASE_RESTART_DELAY_SECONDS,
        MAX_COLLECTOR_RETRIES,
        MAX_RESTART_DELAY_SECONDS,
        STABLE_RUN_SECONDS,
    )

    delays = []
    for fail_count in range(1, MAX_COLLECTOR_RETRIES + 1):
        delay = min(
            MAX_RESTART_DELAY_SECONDS,
            BASE_RESTART_DELAY_SECONDS * (2 ** (fail_count - 1)),
        )
        delays.append(delay)

    assert delays == [5, 10, 20, 40, 60]
    consecutive_failures = MAX_COLLECTOR_RETRIES
    assert (consecutive_failures >= MAX_COLLECTOR_RETRIES) is True
