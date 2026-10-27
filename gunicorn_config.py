# Backward compatibility wrapper for gunicorn_config.py -> gunicorn.conf.py
import os
import runpy

_conf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gunicorn.conf.py")
if os.path.exists(_conf_path):
    _vars = runpy.run_path(_conf_path)
    for _k, _v in _vars.items():
        if not _k.startswith("_"):
            globals()[_k] = _v
