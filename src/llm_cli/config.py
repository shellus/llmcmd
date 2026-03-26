import os
from pathlib import Path

from .utils import fail

try:
    from openai import OpenAI
except ImportError:
    fail("请安装 openai 库: pip install openai")


def load_env_file():
    config_file = Path.home() / ".config/llm-api/.env"
    config = {}
    if config_file.exists():
        with open(config_file, encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()
    return config_file, config


def get_config_value(name, config):
    return os.getenv(name) or config.get(name)


def resolve_model(mode, config, explicit_model=None):
    if explicit_model:
        return explicit_model

    chains = {
        "chat": ["CHAT_MODEL", "MODEL"],
        "text": ["CHAT_MODEL", "MODEL"],
        "image": ["IMAGE_MODEL", "MODEL"],
        "audio": ["AUDIO_MODEL", "MODEL"],
        "video": ["VIDEO_MODEL", "MODEL"],
    }

    for name in chains[mode]:
        value = get_config_value(name, config)
        if value:
            return value
    return None


def load_config(mode, explicit_model=None):
    config_file, config = load_env_file()
    api_key = get_config_value("API_KEY", config)
    base_url = get_config_value("BASE_URL", config)
    model = resolve_model(mode, config, explicit_model=explicit_model)

    if not api_key or not base_url:
        fail(
            f"缺少 API_KEY 或 BASE_URL，请在 {config_file} 中配置或设置环境变量"
        )
    if not model:
        fail(f"缺少 {mode} 模式模型配置，请检查环境变量或 {config_file}")

    return api_key, base_url, model, config


def get_mode_concurrency(mode, config, default=4):
    shared = get_config_value("LLM_CONCURRENCY", config)
    if shared is not None:
        raw = shared
    else:
        legacy_names = {
            "chat": "OPENAI_CHAT_CONCURRENCY",
            "text": "OPENAI_CHAT_CONCURRENCY",
            "image": "OPENAI_IMAGE_CONCURRENCY",
            "video": "OPENAI_VIDEO_CONCURRENCY",
        }
        raw = get_config_value(legacy_names.get(mode), config) if legacy_names.get(mode) else None
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail(f"{mode} 模式并发配置必须是整数，当前为: {raw}")
    if value <= 0:
        fail(f"{mode} 模式并发配置必须大于 0，当前为: {value}")
    return value


def create_client(mode, explicit_model=None):
    api_key, base_url, model, config = load_config(mode, explicit_model=explicit_model)
    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model, config


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
