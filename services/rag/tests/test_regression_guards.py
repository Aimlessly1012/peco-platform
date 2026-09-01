"""测试基建自身的回归契约（M17 组 1）。

这个文件测的不是业务，是**测试环境本身**：护栏在不在、超时配没配、夹具有没有
互相 import。它们坏掉的表现是"测试照样绿，但绿得没有意义"——所以要显式钉住。
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import settings
from tests import conftest as ct

SERVICE_DIR = Path(__file__).resolve().parent.parent          # services/rag
# 再上两级才是仓库根。M16 并入 peco-platform 后这里从一级改成两级——写错不会报错，
# 只会让下面几条 .env 隔离测试走进 pytest.skip，门禁静默失效。
REPO_ROOT = SERVICE_DIR.parent.parent
TESTS_DIR = Path(__file__).resolve().parent


# ---------------- 1.2 .env 隔离 ----------------


def test_settings_use_dummy_credentials():
    """spec 场景: 配置为哑凭据。

    这条也是"从仓库根跑"那个子进程用例的探针——它在别的 CWD 下被单独跑一遍。
    """
    assert settings.embedding_api_key == ct.DUMMY_API_KEY
    assert settings.chat_api_key == ct.DUMMY_API_KEY
    assert settings.embedding_base_url == ct.DEAD_BASE_URL
    assert settings.chat_base_url == ct.DEAD_BASE_URL


def test_rerank_stays_disabled():
    """rerank 三项留空 = 关闭。给哑值会把 rerank_enabled 翻成 True，整片行为跟着变。"""
    assert settings.rerank_enabled is False


def test_object_storage_stays_disabled():
    """默认关存储：绝大多数用例建立在 storage_enabled() 为 False 之上。"""
    from app.services.storage.minio_client import storage_enabled

    assert storage_enabled() is False


def test_real_env_file_is_not_loaded():
    """仓库根的 .env 里是真 key；无论如何都不能出现在 settings 里。"""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        pytest.skip("仓库根没有 .env，这条没有可比对的对象")

    real = dict(
        re.findall(r"^([A-Z0-9_]+)=(.*)$", env_file.read_text(), re.M)
    )
    for key, attr in (
        ("EMBEDDING_API_KEY", "embedding_api_key"),
        ("CHAT_API_KEY", "chat_api_key"),
        ("RERANK_API_KEY", "rerank_api_key"),
    ):
        value = (real.get(key) or "").strip()
        if value:
            # 不打印任何一边的值——只断言它们不相等
            assert getattr(settings, attr) != value, f"{key} 泄漏进了测试配置"


def test_pytest_from_repo_root_is_safe():
    """spec 场景: 从仓库根误跑不打真实 API。

    真的在仓库根起一个 pytest 子进程跑上面那条哑凭据断言——这是唯一能证明
    "换个 CWD 护栏依然生效"的方式，靠读代码是证不出来的。
    """
    if not (REPO_ROOT / ".env").exists():
        pytest.skip("仓库根没有 .env，这个场景不成立")

    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "services/rag/tests/test_regression_guards.py::test_settings_use_dummy_credentials",
         "-q", "--no-cov", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=90,
    )

    assert result.returncode == 0, (
        "从仓库根跑时护栏失效了：\n" + result.stdout[-2000:] + result.stderr[-2000:]
    )


# ---------------- 1.3 禁外网 ----------------


def test_outbound_socket_is_blocked():
    """单测档不许打外网：误配一个真 key 也打不出去。"""
    import socket

    import pytest_socket

    with pytest.raises(pytest_socket.SocketConnectBlockedError):
        socket.create_connection(("api.openai.com", 443), timeout=2)


def test_localhost_socket_is_allowed():
    """本机放行：sqlite 之外的本地组件（集成档的 Neo4j/MinIO）还要用。"""
    import socket

    # 连一个几乎必然关闭的本机端口：放行的证据是"连接被拒"而不是"被拦截"
    with pytest.raises(OSError) as excinfo:
        socket.create_connection(("127.0.0.1", 1), timeout=1)
    assert "SocketBlocked" not in type(excinfo.value).__name__


# ---------------- 1.1 超时 ----------------


def test_global_timeout_is_configured(request):
    assert int(request.config.getini("timeout")) == 120


def test_integration_items_get_a_wider_timeout():
    """集成用例放宽到 300s：起容器 + 建图本来就比单测慢一个量级。"""

    class FakeItem:
        def __init__(self, markers):
            self._markers = markers
            self.added = []

        def get_closest_marker(self, name):
            return object() if name in self._markers else None

        def add_marker(self, marker):
            self.added.append(marker)

    integration = FakeItem({"integration"})
    plain = FakeItem(set())
    already_set = FakeItem({"integration", "timeout"})

    ct.pytest_collection_modifyitems([integration, plain, already_set])

    assert integration.added and integration.added[0].args == (ct.INTEGRATION_TIMEOUT,)
    assert plain.added == []          # 单测保持全局 120s
    assert already_set.added == []    # 用例自己标了 timeout 就不要覆盖它


# ---------------- 1.4 依赖不可达探测 ----------------


def test_port_open_reports_closed_port():
    assert ct.port_open("127.0.0.1", 1, timeout=0.5) is False


def test_port_open_caches_results():
    ct._reachable_cache.clear()
    ct.port_open("127.0.0.1", 1, timeout=0.5)
    assert ("127.0.0.1", 1) in ct._reachable_cache


def test_bolt_target_follows_settings(monkeypatch):
    """探测地址跟着配置走，不是写死 localhost:7687。"""
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://graph-host:7000")

    assert ct._bolt_target() == ("graph-host", 7000)


def test_bolt_target_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://")

    assert ct._bolt_target() == ct.NEO4J_DEFAULT_BOLT


# ---------------- 1.5 夹具收敛 ----------------

# _index_fixture 的两个引用方属于 M17 组 3（3.2）的收尾，不归本包；
# 它们改完之后这个集合会自然缩成空，断言用子集关系所以两种状态都是绿的
KNOWN_PENDING_CROSS_IMPORTS = {
    "test_impact_integration.py",
    "test_report_integration.py",
}


def test_test_files_do_not_import_each_other():
    """spec 场景: 共享夹具重构不跨文件断链。

    测试文件互相 import 会让"改 A 的实现顺手碰坏 B"，夹具要么在 helpers 要么在
    conftest（从 conftest import 是允许的）。
    """
    offenders = {
        path.name
        for path in TESTS_DIR.glob("test_*.py")
        if re.search(r"^from tests\.test_", path.read_text(), re.M)
    }

    assert offenders <= KNOWN_PENDING_CROSS_IMPORTS, (
        f"新增了跨测试文件 import：{sorted(offenders - KNOWN_PENDING_CROSS_IMPORTS)}"
    )


def test_shared_report_fixtures_live_in_helpers():
    from tests.helpers.report import FakeLLM, make_edges, make_tree

    tree = make_tree()
    assert tree.modules and make_edges() is not None
    assert FakeLLM().flow_returns


def test_shared_repo_fixtures_live_in_helpers(tmp_path):
    from tests.helpers.repos import commit_all, existing, make_repo

    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")

    assert len(commit_all(repo, "init")) == 40
    assert existing(["a.py"])["a.py"].path == "a.py"


def test_a_hanging_test_is_actually_interrupted(tmp_path):
    """spec 场景: 挂死用例被超时中断。

    配置项存在不等于它真会开枪。这里生成一个必然挂死的用例、用很短的超时跑一遍
    子进程，断言它是被超时打断的、而且同文件里的另一条照样跑完——
    "其余用例继续执行"也是场景的一部分。

    不把挂死用例留在主测试集里：那会让每一轮都白烧一个超时。
    """
    probe = tmp_path / "test_hang_probe.py"
    probe.write_text(
        "import time\n"
        "def test_hangs():\n"
        "    time.sleep(30)\n"
        "def test_still_runs():\n"
        "    assert True\n"
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-p", "no:cacheprovider",
         "--timeout=1", "--no-cov", "-q"],
        cwd=SERVICE_DIR, capture_output=True, text=True, timeout=90,
    )

    assert result.returncode != 0
    assert "Timeout" in result.stdout or "timeout" in result.stdout.lower()
    assert "1 failed, 1 passed" in result.stdout, result.stdout[-1500:]


def test_integration_tests_skip_when_neo4j_is_unreachable():
    """spec 场景: Neo4j 未启动时集成用例跳过（skipped 带原因，不是连接异常失败）。

    不去停本机容器（别的会话正在用），改成用环境变量把 bolt 地址指到一个关闭的
    端口跑一遍子进程——护栏走的是同一段代码，证明力一样。
    """
    import os

    env = {**os.environ, "NEO4J_URI": "bolt://127.0.0.1:1"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_pipeline_integration.py",
         "-m", "integration", "-q", "--no-cov", "-p", "no:cacheprovider", "-rs"],
        cwd=SERVICE_DIR, capture_output=True, text=True, timeout=120, env=env,
    )

    assert result.returncode == 0, "依赖不可达应当 skip 而不是失败\n" + result.stdout[-1500:]
    assert "skipped" in result.stdout
    assert "Neo4j 不可达" in result.stdout, result.stdout[-1500:]
