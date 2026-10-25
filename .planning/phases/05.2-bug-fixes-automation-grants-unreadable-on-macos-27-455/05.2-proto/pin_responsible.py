"""pytest plugin for the FIX-17 measurement: pins doctor._responsible_process from the
environment so the budget test can be run with any worst case WITHOUT editing tests/.

    RESP='pid 99999 (this), launched by pid 99999' \
      PYTHONPATH=<this dir> uv run pytest -p pin_responsible \
      tests/test_doctor.py -k token_budget
"""

import os

from macos_apps_mcp import doctor

_RESP = os.environ.get("RESP")
if _RESP is not None:
    doctor._responsible_process = lambda: _RESP

if os.environ.get("SIZE"):
    import json

    _diag = doctor.diagnose

    def _measured(request=False):
        report = _diag(request)
        print("\nREPORT_CHARS", len(json.dumps(report, ensure_ascii=False)))
        return report

    doctor.diagnose = _measured

if os.environ.get("DUMP"):
    import json as _j

    _diag2 = doctor.diagnose

    def _dump(request=False):
        report = _diag2(request)
        for k, v in report["deployment"].items():
            print(
                "DEP",
                k,
                len(_j.dumps(v, ensure_ascii=False)),
                _j.dumps(v, ensure_ascii=False)[:230],
            )
        for k, v in report.items():
            if k not in ("deployment",):
                print("TOP", k, len(_j.dumps(v, ensure_ascii=False)))
        return report

    doctor.diagnose = _dump
