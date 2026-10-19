import os
import tempfile

# Tests never reach OpenRouter: the demo AI preview only activates with a key in
# the process environment, so remove it for the whole run.
os.environ.pop('OPENROUTER_API_KEY', None)

# Device files (wallet, vehicle SoC, presentation mode, prepaid) never touch the real home directory.
os.environ.setdefault('FLET_APP_STORAGE_DATA', tempfile.mkdtemp(prefix='chargegrid-tests-'))
