import json
from pathlib import Path

from json4win import cli
from json4win.cli import main


def test_mirrors_input_tree(tmp_path: Path, monkeypatch) -> None:
    # The pipeline itself (OCR, LLM) is tested elsewhere; here only the file mirroring.
    monkeypatch.setattr(cli, "process_document", lambda pdf: {})
    inp, out = tmp_path / "input", tmp_path / "output"
    files = ["case1/odwolanie nr 1.pdf", "case1/przelew.PDF", "case 2/pełnomocnictwo.pdf"]
    for f in files:
        (inp / f).parent.mkdir(parents=True, exist_ok=True)
        (inp / f).write_bytes(b"%PDF-1.4\n")
    (inp / "case1/notes.txt").write_text("not a pdf")

    assert main(["--input", str(inp), "--output", str(out)]) == 0

    got = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert got == sorted(Path(f).with_suffix(".json").as_posix() for f in files)
    for p in out.rglob("*.json"):
        assert isinstance(json.loads(p.read_text(encoding="utf-8")), dict)
