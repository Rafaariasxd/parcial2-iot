import os
import sys
import tempfile
from pathlib import Path

carpeta = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(carpeta) / 'prueba.db'}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
