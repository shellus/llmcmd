import json
import os
from pathlib import Path

from .utils import fail, resolve_text


DEFAULT_PI_PROVIDER = "llmcmd"
DEFAULT_PI_API_KEY_ENV = "LLMCMD_PI_API_KEY"
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh")


def default_pi_agent_dir():
    return (Path.home() / ".llm" / "pi-agent").resolve()


def _pi_model_definition(model, *, reasoning=False):
    return {
        "id": model,
        "name": model,
        "reasoning": bool(reasoning),
        "input": ["text", "image"],
        "contextWindow": 128000,
        "maxTokens": 16384,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }


def build_pi_models_config(*, base_url, model, provider_name=DEFAULT_PI_PROVIDER, api_key_env=DEFAULT_PI_API_KEY_ENV, reasoning=False):
    if not base_url:
        fail("pi agent 缺少 base_url 配置")
    if not model:
        fail("pi agent 缺少 model 配置")
    return {
        "providers": {
            provider_name: {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": api_key_env,
                "models": [_pi_model_definition(model, reasoning=reasoning)],
            }
        }
    }


def ensure_pi_models_json(
    *,
    agent_dir,
    base_url,
    model,
    provider_name=DEFAULT_PI_PROVIDER,
    api_key_env=DEFAULT_PI_API_KEY_ENV,
    reasoning=False,
):
    agent_path = Path(agent_dir).expanduser().resolve()
    agent_path.mkdir(parents=True, exist_ok=True)
    models_path = agent_path / "models.json"
    models_config = build_pi_models_config(
        base_url=base_url,
        model=model,
        provider_name=provider_name,
        api_key_env=api_key_env,
        reasoning=reasoning,
    )
    models_path.write_text(json.dumps(models_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return models_path


def build_pi_command(
    *,
    pi_bin,
    model,
    provider_name=DEFAULT_PI_PROVIDER,
    prompt=None,
    system_prompt=None,
    thinking=None,
    session=None,
    session_dir=None,
    no_session=False,
    tools=None,
    no_tools=False,
):
    if no_tools and tools:
        fail("pi agent 不能同时使用 --tools 和 --no-tools")
    if thinking and thinking not in THINKING_LEVELS:
        fail(f"pi agent 不支持的 thinking 级别: {thinking}")

    command = [pi_bin, "--provider", provider_name, "--model", f"{provider_name}/{model}"]
    if system_prompt:
        command.extend(["--system-prompt", resolve_text(system_prompt)])
    if thinking:
        command.extend(["--thinking", thinking])
    if no_session:
        command.append("--no-session")
    elif session:
        command.extend(["--session", session])
    if session_dir:
        command.extend(["--session-dir", session_dir])
    if no_tools:
        command.append("--no-tools")
    elif tools:
        command.extend(["--tools", tools])
    if prompt:
        command.append(prompt)
    return command


def build_pi_environment(*, agent_dir, api_key, api_key_env=DEFAULT_PI_API_KEY_ENV):
    if not api_key:
        fail("pi agent 缺少 api_key 配置")
    env = os.environ.copy()
    env["PI_CODING_AGENT_DIR"] = str(Path(agent_dir).expanduser().resolve())
    env[api_key_env] = api_key
    env.setdefault("PI_SKIP_VERSION_CHECK", "1")
    return env


def run_pi_agent(
    *,
    config,
    resolved_model,
    prompt=None,
    system_prompt=None,
    pi_bin="pi",
    agent_dir=None,
    session=None,
    session_dir=None,
    no_session=False,
    tools=None,
    no_tools=False,
    thinking=None,
    reasoning=None,
):
    provider = dict((config or {}).get("provider") or {})
    base_url = provider.get("base_url")
    api_key = provider.get("api_key")
    resolved_agent_dir = Path(agent_dir).expanduser().resolve() if agent_dir else default_pi_agent_dir()
    resolved_reasoning = bool(reasoning) if reasoning is not None else bool(thinking and thinking != "off")

    ensure_pi_models_json(
        agent_dir=resolved_agent_dir,
        base_url=base_url,
        model=resolved_model,
        reasoning=resolved_reasoning,
    )
    command = build_pi_command(
        pi_bin=pi_bin,
        model=resolved_model,
        prompt=prompt,
        system_prompt=system_prompt,
        thinking=thinking,
        session=session,
        session_dir=session_dir,
        no_session=no_session,
        tools=tools,
        no_tools=no_tools,
    )
    env = build_pi_environment(agent_dir=resolved_agent_dir, api_key=api_key)
    try:
        os.execvpe(command[0], command, env)
    except FileNotFoundError as exc:
        fail(f"未找到 pi 可执行文件: {pi_bin}")  # pragma: no cover
    except OSError as exc:
        fail(f"启动 pi 失败: {exc}")  # pragma: no cover
