"""Regression: out-of-order completion of overlapping ``_compress_context`` calls
must not corrupt ``_active_compression_commit_fence``.

The fence slot used to be a save/restore cell: attempt B saved previous=A and
published B. When A completed first, its finally popped the slot, deleting B's
live fence mid-attempt (hard_interrupt lost the handle serializing cancel
admission against B's begin_commit). B's finally then republished A's dead
fence, which lingered until the next compression. The slot must instead track
the newest *live* attempt: a registration stack where each attempt removes only
its own entry.
"""

import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent import compression_facade
from agent import conversation_compression
from agent.conversation_compression import CompressionCommitFence
from hermes_state import SessionDB


def _build_agent(db: SessionDB, session_id: str):
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
        from run_agent import AIAgent

        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="test/model",
            platform="telegram",
            quiet_mode=True,
            session_db=db,
            session_id=session_id,
            skip_context_files=True,
            skip_memory=True,
        )
    compressor = MagicMock()
    compressor.compression_count = 0
    compressor.last_prompt_tokens = 0
    compressor.last_completion_tokens = 0
    compressor._last_summary_error = None
    compressor._last_compress_aborted = False
    compressor._last_summary_auth_failure = False
    compressor._last_aux_model_failure_model = None
    compressor._last_aux_model_failure_error = None
    agent.context_compressor = compressor
    return agent


def _overlapping_attempts(agent, messages):
    """Drive two _compress_context attempts whose compress_context calls block on
    release events; returns the controls needed to order their completion."""
    fence_a, fence_b = CompressionCommitFence(), CompressionCommitFence()
    entered_a, entered_b = threading.Event(), threading.Event()
    release_a, release_b = threading.Event(), threading.Event()
    errors = []

    def _fake_compress(_agent, _msgs, _sysmsg, *, commit_fence=None, **_kw):
        if commit_fence is fence_a:
            entered_a.set()
            assert release_a.wait(10), "attempt A never released"
        elif commit_fence is fence_b:
            entered_b.set()
            assert release_b.wait(10), "attempt B never released"
        return [{"role": "user", "content": "x"}], "prompt"

    def _attempt(fence):
        try:
            agent._compress_context(messages, "sys", commit_fence=fence)
        except Exception as exc:
            errors.append(exc)

    return fence_a, fence_b, entered_a, entered_b, release_a, release_b, errors, _fake_compress, _attempt


class TestCommitFenceCompletionOrder:
    def test_earlier_attempt_finishing_first_keeps_newer_live_fence(
        self, tmp_path: Path, monkeypatch
    ):
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("S", source="cli")
        agent = _build_agent(db, "S")
        messages = [{"role": "user", "content": "live question"}]

        (fence_a, fence_b, entered_a, entered_b, release_a, release_b,
         errors, fake, attempt) = _overlapping_attempts(agent, messages)
        monkeypatch.setattr(conversation_compression, "compress_context", fake)

        thread_a = threading.Thread(target=attempt, args=(fence_a,), daemon=True)
        thread_b = threading.Thread(target=attempt, args=(fence_b,), daemon=True)
        thread_a.start()
        assert entered_a.wait(5)
        thread_b.start()
        assert entered_b.wait(5)
        assert vars(agent)["_active_compression_commit_fence"] is fence_b

        # A completes while B is still in its try block: B's fence must survive.
        release_a.set()
        thread_a.join(10)
        assert vars(agent).get("_active_compression_commit_fence") is fence_b

        release_b.set()
        thread_b.join(10)
        assert "_active_compression_commit_fence" not in vars(agent)
        assert not errors

    def test_lifo_completion_restores_outer_fence_while_it_runs(
        self, tmp_path: Path, monkeypatch
    ):
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("S", source="cli")
        agent = _build_agent(db, "S")
        messages = [{"role": "user", "content": "live question"}]

        (fence_a, fence_b, entered_a, entered_b, release_a, release_b,
         errors, fake, attempt) = _overlapping_attempts(agent, messages)
        monkeypatch.setattr(conversation_compression, "compress_context", fake)

        thread_a = threading.Thread(target=attempt, args=(fence_a,), daemon=True)
        thread_b = threading.Thread(target=attempt, args=(fence_b,), daemon=True)
        thread_a.start()
        assert entered_a.wait(5)
        thread_b.start()
        assert entered_b.wait(5)

        # B completes first: A's still-running attempt gets its fence back.
        release_b.set()
        thread_b.join(10)
        assert vars(agent).get("_active_compression_commit_fence") is fence_a

        release_a.set()
        thread_a.join(10)
        assert "_active_compression_commit_fence" not in vars(agent)
        assert not errors


def _capture_new_fence(monkeypatch):
    """Stub the progress-timeout runner; return the dict that receives its kwargs."""
    captured = {}

    def _stub_runner(**kw):
        captured.update(kw)
        return (["m"], "p")

    monkeypatch.setattr(
        conversation_compression, "run_compress_context_with_progress_timeout", _stub_runner)
    monkeypatch.setattr(
        conversation_compression, "request_exceeds_model_window", lambda *a, **k: False)
    return captured


class TestStallFallbackFencePublication:
    """``_publish_new_fence`` swaps the owning registration's fence and publishes to the
    slot only while that attempt still holds the top registration."""

    def _drive(self, monkeypatch, agent, registration, fence, lock):
        captured = _capture_new_fence(monkeypatch)
        compression_facade._run_under_progress_timeout(
            agent, lambda *a, **k: (["m"], "p"), [{"role": "user", "content": "x"}], "sys",
            active_fence=fence, registration=registration, fence_registration_lock=lock,
            idle_timeout=1, total_ceiling=2)
        return captured["new_fence"]

    def test_retry_fence_publishes_while_attempt_owns_slot(self, monkeypatch):
        agent = SimpleNamespace()
        lock = threading.RLock()
        fence = CompressionCommitFence()
        registration = compression_facade._CommitFenceRegistration(fence)
        with lock:
            vars(agent)["_compression_commit_fence_stack"] = [registration]
            agent._active_compression_commit_fence = fence

        retry = self._drive(monkeypatch, agent, registration, fence, lock)()

        assert isinstance(retry, CompressionCommitFence)
        assert registration.fence is retry
        assert vars(agent)["_active_compression_commit_fence"] is retry

    def test_retry_fence_does_not_clobber_newer_attempt(self, monkeypatch):
        agent = SimpleNamespace()
        lock = threading.RLock()
        fence = CompressionCommitFence()
        registration = compression_facade._CommitFenceRegistration(fence)
        other_fence = CompressionCommitFence()
        other = compression_facade._CommitFenceRegistration(other_fence)
        with lock:
            vars(agent)["_compression_commit_fence_stack"] = [registration, other]
            agent._active_compression_commit_fence = other_fence

        retry = self._drive(monkeypatch, agent, registration, fence, lock)()

        # The retry still gets its own fresh fence for begin_commit/cancel serialization,
        # but the published slot stays with the newer live attempt.
        assert isinstance(retry, CompressionCommitFence)
        assert registration.fence is retry
        assert vars(agent)["_active_compression_commit_fence"] is other_fence


def test_hard_stop_waits_for_commit_already_admitted(tmp_path: Path) -> None:
    """A surfaced stop never races an untracked post-return transcript commit."""
    from tests.agent.test_compression_concurrent_fork import _build_agent_with_db

    db = SessionDB(db_path=tmp_path / "state.db")
    session_id = "HARD_CANCEL_AFTER_COMMIT_ADMISSION"
    db.create_session(session_id, source="tui")
    agent = _build_agent_with_db(db, session_id)
    agent.compression_in_place = True
    agent._cached_system_prompt = "sys"
    messages = [{"role": "user", "content": f"m{i}"} for i in range(20)]
    commit_started = threading.Event()
    allow_commit = threading.Event()
    stop_started = threading.Event()
    stop_returned = threading.Event()
    original_archive = db.archive_and_compact

    def _blocked_archive(*args, **kwargs):
        commit_started.set()
        assert allow_commit.wait(timeout=30)
        return original_archive(*args, **kwargs)

    db.archive_and_compact = _blocked_archive
    agent.context_compressor.compress.side_effect = lambda *_a, **_kw: [
        {"role": "user", "content": "[CONTEXT COMPACTION] summary"},
        {"role": "user", "content": "tail"},
    ]
    compression_result: dict[str, tuple] = {}
    compression = threading.Thread(
        target=lambda: compression_result.setdefault(
            "value", agent._compress_context(messages, "sys", approx_tokens=120_000)
        ),
        daemon=True,
    )
    compression.start()
    assert commit_started.wait(timeout=15)

    stop = threading.Thread(
        target=lambda: (
            stop_started.set(),
            agent.hard_interrupt("stop after commit admission"),
            stop_returned.set(),
        ),
        daemon=True,
    )
    stop.start()
    assert stop_started.wait(timeout=15)
    assert not stop_returned.wait(timeout=2)
    allow_commit.set()
    compression.join(timeout=15)
    stop.join(timeout=15)

    assert not compression.is_alive()
    assert not stop.is_alive()
    assert stop_returned.is_set()
    assert compression_result["value"][0][0]["content"] == (
        "[CONTEXT COMPACTION] summary"
    )
    assert agent._hard_interrupt_requested.is_set()
    assert db.get_compression_lock_holder(session_id) is None
