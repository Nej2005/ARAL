import time
from types import SimpleNamespace
from pydantic import BaseModel
import pytest
from google.genai import errors as gerrors
from app.config import settings
from app.services import llm

class P(BaseModel):
    a: str

class FakeErr(gerrors.APIError):
    def __init__(self, code):
        Exception.__init__(self, f"err {code}")
        self.code = code

def run(monkeypatch, script, models=("main", "fb")):
    calls = []
    def fake_call(client, model, system, user, schema, label):
        calls.append(model)
        r = script.pop(0)
        if isinstance(r, int): raise FakeErr(r)
        return r
    monkeypatch.setattr(llm, "_call_once", fake_call)
    monkeypatch.setattr(llm, "_client", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(settings, "gemini_model", models[0])
    monkeypatch.setattr(settings, "gemini_fallback_model", models[1] if len(models) > 1 else "")
    return calls

def test_429_then_fallback_ok(monkeypatch):
    calls = run(monkeypatch, [429, 429, 429, 429, 429, '{"a":"x"}'])
    assert llm._gemini_backend("s", "u", P, "t").a == "x" and calls == ["main"] * 5 + ["fb"]

def test_503_on_main_moves_to_fallback(monkeypatch):
    calls = run(monkeypatch, [503, 503, 503, 503, '{"a":"y"}'])
    assert llm._gemini_backend("s", "u", P, "t").a == "y" and calls[-1] == "fb"

def test_429_main_and_503_fallback_reports_busy(monkeypatch):
    run(monkeypatch, [429] * 5 + [503] * 4)
    with pytest.raises(llm.LLMError) as e:
        llm._gemini_backend("s", "u", P, "t")
    assert "overloaded" in str(e.value) and not isinstance(e.value, llm.LLMQuotaExceeded)

def test_429_everywhere_is_quota(monkeypatch):
    run(monkeypatch, [429] * 10)
    with pytest.raises(llm.LLMQuotaExceeded):
        llm._gemini_backend("s", "u", P, "t")

def test_400_fails_fast(monkeypatch):
    calls = run(monkeypatch, [400])
    with pytest.raises(llm.LLMError):
        llm._gemini_backend("s", "u", P, "t")
    assert calls == ["main"]
