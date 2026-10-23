from raceproof.config import Settings
from raceproof.contracts import PatchProposal
from raceproof.model import GeminiRepairModel


def test_gemini_is_the_default_model() -> None:
    assert Settings.model_fields["model_name"].default == "gemini-3.8-flash"


def test_gemini_model_reports_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    available, reason = GeminiRepairModel("gemini-3.8-flash").available()
    assert not available
    assert "GEMINI_API_KEY or GOOGLE_API_KEY" in reason


def test_gemini_accepts_ai_studio_key_and_structured_output(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-sent")
    model = GeminiRepairModel("gemini-3.8-flash")
    available, reason = model.available()
    assert available, reason

    from langchain_google_genai import ChatGoogleGenerativeAI

    chat = ChatGoogleGenerativeAI(model=model.model_name, temperature=0)
    structured = chat.with_structured_output(PatchProposal)
    assert structured is not None
