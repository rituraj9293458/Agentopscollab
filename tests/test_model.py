from pathlib import Path

from raceproof.config import Settings
from raceproof.contracts import InvestigationContext, InvestigationDecision, PatchProposal
from raceproof.model import GeminiInvestigationAgent, GeminiRepairAgent
from raceproof.target import TargetRegistry, load_adapter


def test_gemini_roles_have_separate_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.resolved_investigation_model == "gemini-3.5-flash-lite"
    assert settings.resolved_repair_model == "gemini-3.1-flash-lite"
    assert settings.fallback_model == "gemini-3.8-flash"
    assert settings.enable_model_fallback is False


def test_gemini_key_loads_from_dotenv_without_being_serialized(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=local-secret\n", encoding="utf-8")
    settings = Settings(_env_file=env_file)
    assert settings.gemini_api_key_value == "local-secret"
    assert "local-secret" not in str(settings.gemini_api_key)


def test_default_dotenv_path_is_project_relative_not_cwd() -> None:
    env_file = Settings.model_config["env_file"]
    assert env_file == Path(__file__).resolve().parents[1] / ".env"


def test_gemini_model_reports_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    available, reason = GeminiRepairAgent("gemini-3.8-flash").available()
    assert not available
    assert "GEMINI_API_KEY or GOOGLE_API_KEY" in reason


def test_gemini_accepts_ai_studio_key_and_structured_output(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-sent")
    model = GeminiRepairAgent("gemini-3.8-flash")
    available, reason = model.available()
    assert available, reason

    from langchain_google_genai import ChatGoogleGenerativeAI

    chat = ChatGoogleGenerativeAI(model=model.model_name, temperature=0)
    structured = chat.with_structured_output(PatchProposal)
    assert structured is not None


def test_agents_have_distinct_prompts_structures_and_tool_permissions() -> None:
    investigator = GeminiInvestigationAgent("gemini-3.8-flash")
    repair = GeminiRepairAgent("gemini-3.8-flash")
    assert investigator.system_prompt != repair.system_prompt
    assert investigator.tool_names != repair.tool_names
    assert "select_controlled_experiment" in investigator.tool_names
    assert "read_investigation_handoff" in repair.tool_names
    assert "read_investigation_handoff" not in investigator.tool_names
    assert "select_controlled_experiment" not in repair.tool_names
    assert "patch" not in " ".join(investigator.tool_names)
    assert InvestigationDecision.model_fields["experiment_name"]


def test_investigation_agent_tools_are_bound_to_approved_target_evidence() -> None:
    root = Path(__file__).resolve().parents[1]
    target = TargetRegistry(root / "examples").get("inventory_oversell")
    source_files = {
        path: (target.repository_root / path).read_text(encoding="utf-8")
        for path in target.config.operation.source_files
    }
    context = InvestigationContext(
        target_id=target.config.id,
        target_name=target.config.name,
        target_operation=target.config.operation.callable,
        source_files=source_files,
        schema_ddl=load_adapter(target).schema_ddl(),
        findings=[],
        transaction_boundaries=["one transaction per actor"],
        checkpoints=["after_read"],
        available_experiments=[
            target.config.reproduction_schedule,
            *target.config.investigation_schedules,
        ],
        invariant=target.config.invariant,
    )
    agent = GeminiInvestigationAgent("gemini-3.8-flash")
    tools = {item.name: item for item in agent._tools(context)}
    assert set(tools) == set(agent.tool_names)
    approved = target.config.operation.source_files[0]
    assert "purchase_inventory" in tools["read_approved_source"].invoke({"path": approved})
    assert tools["read_approved_source"].invoke({"path": "../secret"}).startswith("DENIED")
    selected = tools["select_controlled_experiment"].invoke(
        {"name": target.config.reproduction_schedule.name}
    )
    assert selected["approved"] is True
