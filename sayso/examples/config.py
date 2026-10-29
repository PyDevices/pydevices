# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Load the settings the write examples share.

Reads ``write_examples.json`` from this folder and checks that write examples are turned on. The write examples import it; it isn't run on its own.

Needs: CPython, and ``examples/write_examples.json``, copied from ``examples/write_examples.json.example``.

Tested on: CPython 3.12.3 on Linux (WSL2).
"""

import os

from sayso import SpotifyConfigError, config_value


# Where the settings file lives: beside this file.
EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WRITE_EXAMPLES_PATH = os.path.join(EXAMPLES_DIR, "write_examples.json")


def load_write_examples_config(path=None):
    """Return the settings from write_examples.json as a dict."""
    config_path = path or DEFAULT_WRITE_EXAMPLES_PATH

    try:
        import json
    except ImportError:
        raise SpotifyConfigError("json is required to load write example config")

    try:
        with open(config_path) as file:
            data = json.load(file)
    except OSError as error:
        raise SpotifyConfigError(
            "Create {} from examples/write_examples.json.example".format(config_path)
        ) from error

    if not isinstance(data, dict):
        raise SpotifyConfigError("{} must contain a JSON object".format(config_path))

    return data


def write_examples_enabled(config=None, path=None):
    """Say whether write examples are turned on."""
    if config is None:
        config = load_write_examples_config(path)
    return bool(config.get("allow_write_examples"))


def require_write_examples(config=None, path=None):
    """Stop with an error unless write examples are turned on."""
    if config is None:
        config = load_write_examples_config(path)

    if not write_examples_enabled(config):
        raise SpotifyConfigError(
            "Set allow_write_examples to true in examples/write_examples.json to run write examples"
        )


__all__ = (
    "DEFAULT_WRITE_EXAMPLES_PATH",
    "config_value",
    "load_write_examples_config",
    "require_write_examples",
    "write_examples_enabled",
)
