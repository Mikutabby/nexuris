"""Tests offline del actualizador: ranking de modelos y persistencia."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nexuris.core.config as config
import nexuris.update as update


def model(mid: str, ctx: int = 200_000, *, prompt="0", completion="0", tools=True) -> dict:
    return {
        "id": mid,
        "name": mid,
        "context_length": ctx,
        "pricing": {"prompt": prompt, "completion": completion},
        "supported_parameters": ["tools", "temperature"] if tools else ["temperature"],
    }


def test_filters() -> None:
    models = [
        model("good/free-a"),
        model("pay/expensive", prompt="0.000001"),
        model("half/free", completion="0.5"),
        model("notools/free", tools=False),
        model("tiny/ctx", ctx=8_000),
    ]
    ids = [m["id"] for m in update.candidates(models)]
    assert ids == ["good/free-a"], ids
    assert update.is_free(models[0]) and not update.is_free(models[1])
    print("ok filtros (pago, sin tools, contexto chico)")


def test_ranking() -> None:
    models = [
        model("nvidia/huge", ctx=1_000_000),
        model("anthropic/claude-free"),
        model("google/small-free"),
        model("some/preview-free"),
        model("openrouter/free"),
    ]
    ids = [m["id"] for m in update.candidates(models, limit=10)]
    assert ids[0] == "anthropic/claude-free", ids
    assert ids.index("openrouter/free") > 0, ids
    assert ids.index("google/small-free") > ids.index("anthropic/claude-free")
    print("ok ranking (proveedor > contexto, penaliza preview/small/fallback)")


def test_config_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config.CONFIG_DIR = Path(tmp)
        config.USER_CONFIG_PATH = Path(tmp) / "config.json"
        config.save_user_config(model="x/y:free", model_info={"a": 1})
        data = config.load_user_config()
        assert data["model"] == "x/y:free", data
        assert data["model_info"] == {"a": 1}, data
        assert config.USER_CONFIG_PATH.exists()
    print("ok config persistente (escritura atómica y lectura)")


def test_refresh_picks_validated() -> None:
    # bad rankea primero (contexto mayor) para probar que se salta al que falla
    models = [model("bad/model:free", ctx=1_000_000), model("good/model:free")]
    calls: list[str] = []
    saved: dict = {}

    update.fetch_models = lambda timeout=25.0: models
    update.validate_model = lambda mid, key, timeout=30.0: (calls.append(mid) or mid == "good/model:free", "ok")
    update.save_user_config = lambda **kw: saved.update(kw) or Path("/dev/null")

    result = update.refresh_model(api_key="fake", verbose=False)
    assert result["model"] == "good/model:free", result
    assert calls == ["bad/model:free", "good/model:free"], calls
    assert saved["model"] == "good/model:free"
    print("ok refresh valida de a uno hasta encontrar uno que responda")


def test_refresh_all_fail_uses_router() -> None:
    update.fetch_models = lambda timeout=25.0: [model("bad/model:free")]
    update.validate_model = lambda mid, key, timeout=30.0: (False, "429")
    update.save_user_config = lambda **kw: Path("/dev/null")

    result = update.refresh_model(api_key="fake", verbose=False)
    assert result["model"] == update.FALLBACK_MODEL, result
    print("ok si ninguno valida, cae al router gratuito")


def test_git_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        has_repo, state = update.git_status(Path(tmp))
        assert has_repo is False and state == "nogit"
    print("ok detección de repo git")


def main() -> None:
    print("== Nexuris — test del actualizador ==\n")
    test_filters()
    test_ranking()
    test_config_roundtrip()
    test_refresh_picks_validated()
    test_refresh_all_fail_uses_router()
    test_git_detection()
    print("\n✅ Actualizador OK.")


if __name__ == "__main__":
    main()
