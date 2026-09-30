"""TikTok Engine: a short-form media studio built on the Shorts Studio core (`studio`)."""
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ENGINE_ROOT.parent
if str(REPO_ROOT) not in sys.path:  # the core library lives next to this application
    sys.path.insert(0, str(REPO_ROOT))

__version__ = "0.1.0"
