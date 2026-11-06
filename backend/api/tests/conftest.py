import os
import tempfile
from pathlib import Path

# Tests never download the public threat feeds or run the trust models.
os.environ["LINK_THREAT_FEEDS"] = "off"
os.environ["TRUST_MODELS"] = "off"
# Tests clear the case store, so they must never share the database the running app uses.
os.environ["CASE_STORE_PATH"] = str(Path(tempfile.mkdtemp(prefix="trustfeed-tests-")) / "cases.db")
