"""Scope synchronous worker fakes without changing subprocess reader threads."""

import threading
from types import SimpleNamespace


def set_thread_class(monkeypatch, server, thread_class):
    namespace = SimpleNamespace(**{**vars(threading), "Thread": thread_class})
    monkeypatch.setattr(server, "threading", namespace)
    monkeypatch.setattr("agent.memory_provider.threading", namespace)
