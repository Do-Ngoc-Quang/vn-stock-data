import json

import pytest

from pipeline.config import Config
from pipeline.providers import registry
from pipeline.run import main


def test_unknown_provider_lists_valid_names():
    with pytest.raises(ValueError) as e:
        registry.create_provider(Config(provider="khong-co"))
    assert "khong-co" in str(e.value) and "vnstock" in str(e.value)


def test_registered_provider_is_created_from_config(monkeypatch):
    seen = {}

    class Dummy:
        name, version, source = "dummy", "0", "dsrc"

    def factory(cfg):
        seen["cfg"] = cfg
        return Dummy()

    monkeypatch.setitem(registry.PROVIDERS, "dummy", factory)
    cfg = Config(provider="dummy")
    assert isinstance(registry.create_provider(cfg), Dummy)
    assert seen["cfg"] is cfg


def test_vnstock_factory_builds_vnstock_provider():
    from pipeline.providers.vnstock_provider import VnstockProvider

    p = registry.create_provider(Config(provider="vnstock", source="vci"))
    assert isinstance(p, VnstockProvider) and p.source == "vci"


def test_main_exits_2_on_unknown_provider(tmp_path, capsys):
    cfg = tmp_path / "p.json"
    cfg.write_text(json.dumps({"provider": "khong-co"}), encoding="utf-8")
    code = main(["--config", str(cfg), "--data-dir", str(tmp_path / "d"), "--universe", str(tmp_path / "u.txt")])
    assert code == 2
    assert "khong-co" in capsys.readouterr().err
