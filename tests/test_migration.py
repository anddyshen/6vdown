"""数据目录迁移单测：程序目录里的较新库必须优先于 %APPDATA% 旧库。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import constants  # noqa: E402

try:  # PySide6 缺失（纯测试环境）时跳过整个模块
    from src import app as app_mod
    from src.app import _migrate_db_name, _migrate_legacy_data
except Exception:  # pragma: no cover
    app_mod = None
    _migrate_db_name = _migrate_legacy_data = None


def _write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


@unittest.skipIf(app_mod is None, "PySide6 不可用，跳过迁移测试")
class TestDataMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.new_dir = os.path.join(self.tmp.name, "portable", "data")
        self.old_dir = os.path.join(self.tmp.name, "appdata", "C2Down")
        os.makedirs(self.new_dir)
        os.makedirs(self.old_dir)
        self._orig = (app_mod.app_data_dir, app_mod.legacy_data_dirs,
                      constants.is_frozen)
        app_mod.app_data_dir = lambda: self.new_dir
        app_mod.legacy_data_dirs = lambda: [self.old_dir]
        constants.is_frozen = lambda: True

    def tearDown(self):
        (app_mod.app_data_dir, app_mod.legacy_data_dirs,
         constants.is_frozen) = self._orig
        self.tmp.cleanup()

    def test_local_db_wins_over_legacy_appdata(self):
        """程序目录里有较新的 c2down.db 时，不能被更旧的 APPDATA 快照顶掉。"""
        _write(os.path.join(self.new_dir, "c2down.db"), b"NEW-LOCAL")
        _write(os.path.join(self.old_dir, "c2down.db"), b"OLD-APPDATA")
        _migrate_db_name()
        _migrate_legacy_data()
        self.assertEqual(_read(os.path.join(self.new_dir, "6vdown.db")),
                         b"NEW-LOCAL")

    def test_legacy_used_when_no_local_db(self):
        """全新安装（程序目录无库）时，仍应从 APPDATA 搬迁旧数据。"""
        _write(os.path.join(self.old_dir, "c2down.db"), b"OLD-APPDATA")
        _migrate_db_name()
        _migrate_legacy_data()
        self.assertEqual(_read(os.path.join(self.new_dir, "6vdown.db")),
                         b"OLD-APPDATA")

    def test_existing_new_db_is_kept(self):
        """已有 6vdown.db 时两次迁移都不得覆盖。"""
        _write(os.path.join(self.new_dir, "6vdown.db"), b"KEEP")
        _write(os.path.join(self.new_dir, "c2down.db"), b"NEW-LOCAL")
        _write(os.path.join(self.old_dir, "c2down.db"), b"OLD-APPDATA")
        _migrate_db_name()
        _migrate_legacy_data()
        self.assertEqual(_read(os.path.join(self.new_dir, "6vdown.db")),
                         b"KEEP")


class TestPortableDataDir(unittest.TestCase):
    """绝对绿色：数据目录只跟随程序目录，不落系统目录。"""

    def test_data_dir_is_next_to_program(self):
        self.assertNotIn("APPDATA", constants.app_data_dir().upper())
        self.assertNotIn("LOCALAPPDATA", constants.app_data_dir().upper())

    def test_source_mode_uses_project_data(self):
        if constants.is_frozen():
            self.skipTest("打包环境")
        self.assertEqual(
            os.path.normcase(constants.app_data_dir()),
            os.path.normcase(os.path.join(constants.project_root(), "data")))


if __name__ == "__main__":
    unittest.main()
