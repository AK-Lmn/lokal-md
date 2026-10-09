import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="rhutest_")
os.environ["RHUSCRIBE_DATA_DIR"] = _tmp
os.environ["RHUSCRIBE_MODELS_DIR"] = str(Path(_tmp) / "models")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rhuscribe import auth, bootstrap, crypto, db  # noqa: E402
from rhuscribe.repo import Store  # noqa: E402
from rhuscribe.safety import refdata  # noqa: E402

crypto.set_kdf_cost(2**10)  # fast KDF for tests only

PW = "Str0ngPassw0rd!"


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    bootstrap.init(c)
    yield c
    c.close()


@pytest.fixture()
def admin_ctx(conn):
    user, recovery, vault = auth.first_run_setup(conn, "admin", "Admin User", PW)
    return conn, user, vault, recovery


@pytest.fixture()
def clinician_store(admin_ctx):
    conn, admin, vault, _ = admin_ctx
    dek = _dek(conn, "admin")
    u = auth.create_user(conn, admin, dek, "drcruz", "Dr. Test Cruz", "clinician", PW, credentials="MD (synthetic)", license_no="SYN-0000")
    user, vault2 = auth.login(conn, "drcruz", PW)
    return Store(conn, vault2, user)


def _dek(conn, username, pw=PW):
    r = conn.execute("SELECT wrapped_dek FROM users WHERE username=?", (username,)).fetchone()
    return crypto.unwrap_dek(r["wrapped_dek"], pw)


@pytest.fixture()
def ix(conn):
    return refdata.load_active_index(conn)
