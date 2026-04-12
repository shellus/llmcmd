import os
import re
from pathlib import Path

from .utils import fail

try:
    import yaml
except ImportError:
    yaml = None

try:
    from openai import OpenAI
except ImportError:
    fail("请安装 openai 库: pip install openai")


ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
DEFAULT_CONFIG_DIR = Path.home() / ".llm"
DEFAULT_ENV_FILE = DEFAULT_CONFIG_DIR / ".env"
DEFAULT_YAML_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


def _normalize_mode(mode):
    return "chat" if mode == "text" else mode


def config_paths():
    config_dir = Path.home() / ".llm"
    return {
        "config_dir": config_dir,
        "env_file": config_dir / ".env",
        "config_file": config_dir / "config.yaml",
    }


def load_env_file(path=None):
    env_file = Path(path).expanduser() if path else config_paths()["env_file"]
    values = {}
    if env_file.exists():
        with env_file.open(encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return env_file, values


def apply_env_overrides(values):
    for key, value in values.items():
        os.environ.setdefault(key, value)


def _ensure_yaml_available():
    if yaml is None:
        fail("YAML 配置需要 pyyaml，请安装: pip install pyyaml")


def _expand_env_placeholders(value):
    if isinstance(value, dict):
        return {key: _expand_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_placeholders(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match):
        name = match.group(1)
        if name not in os.environ:
            fail(f"YAML 配置引用了未定义环境变量: {name}")
        return os.environ[name]

    return ENV_VAR_PATTERN.sub(replace, value)


def load_runtime_config():
    paths = config_paths()
    _, env_values = load_env_file(paths["env_file"])
    apply_env_overrides(env_values)
    _ensure_yaml_available()

    config_file = paths["config_file"]
    if not config_file.exists():
        fail(f"缺少配置文件: {config_file}")

    try:
        with config_file.open(encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except FileNotFoundError:
        fail(f"缺少配置文件: {config_file}")
    except IsADirectoryError:
        fail(f"配置路径不是文件: {config_file}")
    except UnicodeDecodeError:
        fail(f"配置文件不是有效的 UTF-8 文本: {config_file}")
    except yaml.YAMLError as exc:
        fail(f"YAML 解析失败: {config_file} ({exc})")
    except OSError as exc:
        fail(f"读取配置文件失败: {config_file} ({exc})")

    if not isinstance(data, dict):
        fail("config.yaml 顶层必须是对象")

    config = _expand_env_placeholders(data)
    config["paths"] = paths
    config.setdefault("providers", {})
    config.setdefault("modes", {})
    config.setdefault("reference_transports", {})
    return config


def _provider_mode_config(provider, mode):
    provider_modes = provider.get("modes") or {}
    mode_config = provider_modes.get(mode) or {}
    if mode_config and not isinstance(mode_config, dict):
        fail(f"provider {provider.get('name') or '<unknown>'} 的 {mode} 配置必须是对象")
    return dict(mode_config)


def _provider_models(provider):
    models = provider.get("models") or {}
    if not isinstance(models, dict):
        fail(f"provider {provider.get('name') or '<unknown>'} 的 models 配置必须是对象")
    return models


def _resolve_provider_model(provider, mode, requested_model=None):
    matches = []
    for model_name, model_config in _provider_models(provider).items():
        model_type = model_config.get("type")
        alias = model_config.get("alias")
        if model_type and _normalize_mode(model_type) != mode:
            continue
        if requested_model is None:
            continue
        if requested_model == model_name or requested_model == alias:
            matches.append((model_name, dict(model_config or {})))
    if requested_model is None:
        return None, None
    if len(matches) > 1:
        names = ", ".join(name for name, _ in matches)
        fail(f"模型 {requested_model} 在 provider {provider.get('name')} 中匹配到多个定义: {names}")
    if matches:
        return matches[0]
    return None, None


def _resolve_provider_for_model(mode, explicit_model, config, provider_name=None):
    if provider_name:
        provider = dict(((config.get("providers") or {}).get(provider_name)) or {})
        if not provider:
            fail(f"{mode} 模式引用了不存在的 provider: {provider_name}")
        provider["name"] = provider_name
        model_name, model_config = _resolve_provider_model(provider, mode, explicit_model)
        if model_name:
            return provider_name, model_name, model_config
        return provider_name, explicit_model, None

    matches = []
    for provider_name, provider in (config.get("providers") or {}).items():
        provider_copy = dict(provider or {})
        provider_copy["name"] = provider_name
        model_name, model_config = _resolve_provider_model(provider_copy, mode, explicit_model)
        if model_name:
            matches.append((provider_name, model_name, model_config))
    if len(matches) > 1:
        names = ", ".join(name for name, _, _ in matches)
        fail(f"模型别名 {explicit_model} 在多个 provider 中重复定义: {names}")
    if matches:
        provider_name, model_name, model_config = matches[0]
        return provider_name, model_name, model_config
    return None, explicit_model, None


def _runtime_model_override(mode):
    env_names = {
        "chat": ["CHAT_MODEL", "MODEL"],
        "text": ["CHAT_MODEL", "MODEL"],
        "image": ["IMAGE_MODEL", "MODEL"],
        "audio": ["AUDIO_MODEL", "MODEL"],
        "video": ["VIDEO_MODEL", "MODEL"],
    }
    for name in env_names.get(mode, []):
        value = os.getenv(name)
        if value:
            return value
    return None


def _default_protocol_for_mode(mode):
    if mode == "video":
        return "openai-videos"
    if mode in {"chat", "image", "audio"}:
        return "openai-chat-completions"
    return f"openai-{mode}"


def resolve_mode_settings(mode, config, explicit_model=None, explicit_provider=None):
    mode = _normalize_mode(mode)
    providers = config.get("providers") or {}
    global_mode = dict((config.get("modes") or {}).get(mode) or {})

    provider_name = explicit_provider or global_mode.get("provider") or config.get("default_provider")
    model = global_mode.get("model") or config.get("default_model")
    model_config = None
    runtime_model = _runtime_model_override(mode)
    if runtime_model and not explicit_model:
        model = runtime_model

    if explicit_model:
        matched_provider, mapped_model, matched_model_config = _resolve_provider_for_model(
            mode,
            explicit_model,
            config,
            provider_name=explicit_provider,
        )
        if matched_provider:
            provider_name = matched_provider
            model = mapped_model
            model_config = matched_model_config
        else:
            model = explicit_model

    if not provider_name:
        fail(f"{mode} 模式缺少 provider 配置，请检查 config.yaml")
    if provider_name not in providers:
        fail(f"{mode} 模式引用了不存在的 provider: {provider_name}")

    provider = dict(providers[provider_name] or {})
    provider["name"] = provider_name
    runtime_base_url = os.getenv("BASE_URL")
    runtime_api_key = os.getenv("API_KEY")
    if runtime_base_url:
        provider["base_url"] = runtime_base_url
    if runtime_api_key:
        provider["api_key"] = runtime_api_key
    provider_mode = _provider_mode_config(provider, mode)
    runtime_model_unmapped = bool(runtime_model) and not explicit_model and model == runtime_model and model_config is None
    explicit_model_unmapped = bool(explicit_model) and model == explicit_model and model_config is None
    if model_config is None:
        resolved_model_name, resolved_model_config = _resolve_provider_model(provider, mode, model)
        if resolved_model_name:
            model = resolved_model_name
            model_config = resolved_model_config

    if not model:
        fail(f"{mode} 模式缺少 model 配置，请检查 config.yaml")
    if model_config is None and not explicit_model_unmapped and not runtime_model_unmapped:
        fail(f"{mode} 模式模型未在 provider {provider_name} 中定义: {model}")

    base_url = provider.get("base_url")
    api_key = provider.get("api_key")
    if not base_url or not api_key:
        fail(f"provider {provider_name} 缺少 base_url 或 api_key 配置")

    mode_settings = {
        "name": mode,
        "provider": provider_name,
        "protocol": (model_config or {}).get("protocol")
        or global_mode.get("protocol")
        or provider_mode.get("protocol")
        or _default_protocol_for_mode(mode),
        "model": model,
        "concurrency": (model_config or {}).get("concurrency") or global_mode.get("concurrency") or provider_mode.get("concurrency") or config.get("concurrency"),
        "reference_transport": (model_config or {}).get("reference_transport") or global_mode.get("reference_transport") or provider_mode.get("reference_transport"),
        "request": dict((model_config or {}).get("request") or {}),
        "defaults": dict((model_config or {}).get("defaults") or {}),
        "raw": global_mode,
    }

    reference_transport_name = mode_settings["reference_transport"]
    reference_transports = config.get("reference_transports") or {}
    reference_transport = None
    if reference_transport_name:
        if reference_transport_name not in reference_transports:
            fail(f"{mode} 模式引用了不存在的 reference_transport: {reference_transport_name}")
        reference_transport = dict(reference_transports[reference_transport_name] or {})
        reference_transport["name"] = reference_transport_name

    return {
        "paths": config.get("paths") or {},
        "provider": provider,
        "mode": mode_settings,
        "model": model,
        "model_config": model_config,
        "reference_transport": reference_transport,
        "reference_transports": reference_transports,
        "providers": providers,
        "modes": config.get("modes") or {},
        "default_provider": config.get("default_provider"),
        "default_model": config.get("default_model"),
        "concurrency": config.get("concurrency"),
    }


def get_config_value(name, config):
    if name == "BASE_URL":
        return (config.get("provider") or {}).get("base_url") or config.get("BASE_URL") or config.get("base_url")
    if name == "API_KEY":
        return (config.get("provider") or {}).get("api_key") or config.get("API_KEY") or config.get("api_key")
    if name == "LLM_CONCURRENCY":
        return (config.get("mode") or {}).get("concurrency") or config.get("concurrency") or config.get(name)
    return os.getenv(name) or config.get(name)


def get_mode_concurrency(mode, config, default=4):
    raw = get_config_value("LLM_CONCURRENCY", config)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail(f"{mode} 模式并发配置必须是整数，当前为: {raw}")
    if value <= 0:
        fail(f"{mode} 模式并发配置必须大于 0，当前为: {value}")
    return value


def create_client(mode, explicit_model=None, explicit_provider=None):
    runtime = load_runtime_config()
    resolved = resolve_mode_settings(mode, runtime, explicit_model=explicit_model, explicit_provider=explicit_provider)
    client = OpenAI(
        api_key=resolved["provider"]["api_key"],
        base_url=resolved["provider"]["base_url"],
    )
    return client, resolved["model"], resolved


def write_env_value(config_file, key, value):
    path = Path(config_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    output_lines = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            current_key, _ = line.split("=", 1)
            if current_key.strip() == key:
                output_lines.append(f"{key}={value}")
                replaced = True
                continue
        output_lines.append(line)

    if not replaced:
        output_lines.append(f"{key}={value}")

    path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
