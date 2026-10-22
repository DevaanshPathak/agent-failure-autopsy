"""Vercel entrypoint (docs/deploy.md): Vercel's Python runtime serves a module-level `app`.

Locally, run `uvicorn --factory app.main:create_app` instead; importing app.main builds nothing.
"""

import os

# The Anthropic SDK looks for a config dir under $HOME, which a serverless sandbox may not have.
os.environ.setdefault("ANTHROPIC_CONFIG_DIR", "/tmp/anthropic")

from app.main import create_app  # noqa: E402

app = create_app()
