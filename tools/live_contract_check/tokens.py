"""Imprime JSON com tokens locais de teste (dono, motorista, rival) para ``exercise.py``."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DRIVER, OWNER, RIVAL, token

print(json.dumps({"owner": token(OWNER), "driver": token(DRIVER), "rival": token(RIVAL)}))
