"""Shared credential path for wechat-article-claw."""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILENAME = "wechat_env.json"


def config_dir() -> Path:
    env = os.environ.get("LLM_CLAW_ENV_PATH", "").strip()
    if env:
        return Path(os.path.expanduser(env))
    return Path(__file__).resolve().parent


def env_file_path() -> Path:
    return config_dir() / ENV_FILENAME
