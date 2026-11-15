#!/usr/bin/env python3
"""Suite wrappers must contain legacy Path.home()/Wine outputs inside the receipt."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import run_suite_parallel as runner


if __name__ == '__main__':
    try:
        root = Path(__file__).resolve().parents[1] / 'runtime/suite-sandbox-gate'
        with patch.dict(os.environ):
            runner.sandbox_environment(root)
            for key in ['HOME', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'TMPDIR']:
                path = Path(os.environ[key]).resolve()
                assert path.is_relative_to(root.resolve()) and path.is_dir(), key + ' escapes suite receipt'
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
