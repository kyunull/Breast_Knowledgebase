from __future__ import annotations

import json

from scripts import audit_bilingual_terms


def test_audit_script_rejects_malformed_term_values(tmp_path, monkeypatch, capsys):
    glossary_path = tmp_path / "bilingual_terms.json"
    glossary_path.write_text(
        json.dumps({"terms": {"乳腺癌": "breast cancer"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_bilingual_terms, "GLOSSARY_PATH", glossary_path)

    exit_code = audit_bilingual_terms.main()

    assert exit_code == 1
    assert "list of strings" in capsys.readouterr().out
