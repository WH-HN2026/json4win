import os

from json4win import env


def test_load_env_keeps_existing_and_strips(tmp_path, monkeypatch):
    f = tmp_path / ".env.local"
    f.write_text(
        "# comment\nA_SET=from_file\nB_NEW='quoted'  # trailing\n\nC_EMPTY=\n", encoding="utf-8"
    )
    monkeypatch.setenv("A_SET", "from_env")
    monkeypatch.delenv("B_NEW", raising=False)
    monkeypatch.delenv("C_EMPTY", raising=False)
    env.load_env(f)
    assert os.environ["A_SET"] == "from_env"
    assert os.environ["B_NEW"] == "quoted"
    assert env.get("C_EMPTY", "default") == "default"


def test_cache_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("JSON4WIN_CACHE_DIR", str(tmp_path / "c"))
    assert env.cache_dir() == tmp_path / "c"
