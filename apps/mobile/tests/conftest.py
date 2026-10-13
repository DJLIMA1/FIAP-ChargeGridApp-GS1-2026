import os

# Tests never reach OpenRouter: the demo AI preview only activates with a key in
# the process environment, so remove it for the whole run.
os.environ.pop('OPENROUTER_API_KEY', None)
