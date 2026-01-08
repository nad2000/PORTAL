#!/usr/bin/env python
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import os
import sys
from pathlib import Path
import importlib

if __name__ == "__main__":
    env_name = os.getenv("ENV", "local")
    # fall back to local if
    try:
        importlib.import_module(f"config.settings.{env_name}")
    except ModuleNotFoundError:
        parent_dir = os.path.basename(os.getcwd())
        env_name = parent_dir if parent_dir in ["dev", "prod", "test"] else "local"

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"config.settings.{env_name}")

    try:
        from django.core.management import execute_from_command_line
    except ImportError:
        # The above import may fail for some other reason. Ensure that the
        # issue is really that Django is missing to avoid masking other
        # exceptions on Python 2.
        try:
            import django  # noqa
        except ImportError:
            raise ImportError(
                "Couldn't import Django. Are you sure it's installed and "
                "available on your PYTHONPATH environment variable? Did you "
                "forget to activate a virtual environment?"
            )

        raise

    # This allows easy placement of apps within the interior
    # portal directory.
    current_path = Path(__file__).parent.resolve()
    sys.path.append(str(current_path / "portal"))

    execute_from_command_line(sys.argv)
