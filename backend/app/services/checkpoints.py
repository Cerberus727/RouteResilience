"""Checkpoint inspection and (optional) architecture compatibility checks.

* Checkpoints are opened with `torch.load(weights_only=True)`, which does not run
  pickled code.
* A checkpoint is only loaded into an architecture whose key layout matches it,
  and only with `strict=True`. Every failure is reported as a diagnostic and
  never raised to the client.
* torch and segmentation-models-pytorch are optional dependencies.
"""

from __future__ import annotations

import statistics
import threading
import time
from collections import Counter
from pathlib import Path

_lock = threading.Lock()
_inspect_cache: dict[tuple, dict] = {}
_model_cache: dict[tuple, object] = {}

SIGNATURES = {
    # family -> (required key prefixes, description)
    "smp_deeplabv3plus": ({"encoder", "decoder", "segmentation_head"}, "segmentation_models_pytorch DeepLabV3+ (encoder/decoder/segmentation_head)"),
    "unext": ({"encoder1", "patch_embed3", "block1", "final"}, "UNeXt (Valanarasu & Patel 2022) layer naming"),
    "densed_dsaspp": ({"backbone", "aspp", "low_level_proj", "se", "decoder"}, "Xception-style backbone + dense depthwise-separable ASPP + SE + DeepLabV3+-style decoder"),
}


def _torch():
    try:
        import torch  # noqa: WPS433

        return torch, None
    except Exception as exc:  # pragma: no cover - depends on environment
        return None, f"PyTorch is not installed ({type(exc).__name__}); install backend/requirements-ml.txt to inspect checkpoints."


def _load_state_dict(path: Path):
    torch, err = _torch()
    if torch is None:
        return None, err
    try:
        sd = torch.load(str(path), map_location="cpu", weights_only=True)
    except Exception as exc:
        return None, f"torch.load(weights_only=True) failed: {type(exc).__name__}: {str(exc)[:300]}"
    if isinstance(sd, dict) and "state_dict" in sd and isinstance(sd["state_dict"], dict):
        sd = sd["state_dict"]
    if not isinstance(sd, dict) or not sd:
        return None, "File does not contain a state_dict (mapping of parameter names to tensors)."
    return sd, None


def inspect_checkpoint(path: Path) -> dict:
    """Structural summary of a checkpoint (cached by mtime)."""
    st = path.stat()
    key = (str(path), st.st_mtime_ns)
    with _lock:
        if key in _inspect_cache:
            return dict(_inspect_cache[key])
    info: dict = {"file": path.name, "size_bytes": st.st_size, "loaded": False}
    sd, err = _load_state_dict(path)
    if sd is None:
        info["error"] = err
    else:
        torch, _ = _torch()
        tensors = {k: v for k, v in sd.items() if torch.is_tensor(v)}
        buffers = ("running_mean", "running_var", "num_batches_tracked")
        prefixes = Counter(k.split(".")[0] for k in tensors)
        family = next((fam for fam, (req, _) in SIGNATURES.items() if req <= set(prefixes)), None)
        info.update(
            loaded=True,
            num_tensors=len(tensors),
            num_parameters=int(sum(v.numel() for k, v in tensors.items() if not k.endswith(buffers))),
            num_values_including_buffers=int(sum(v.numel() for v in tensors.values())),
            dtypes=sorted({str(v.dtype).replace("torch.", "") for v in tensors.values()}),
            top_level_modules=dict(prefixes.most_common()),
            detected_family=family,
            detected_description=SIGNATURES[family][1] if family else None,
        )
    with _lock:
        _inspect_cache[key] = info
    return dict(info)


def _build_deeplab():
    import segmentation_models_pytorch as smp  # optional

    # Identical arguments to Phase I build_model() for FAMILY == "smp_deeplabv3",
    # except encoder_weights=None (the checkpoint provides every weight).
    return smp.DeepLabV3Plus(
        encoder_name="resnet34", encoder_weights=None, encoder_output_stride=16, decoder_channels=256,
        decoder_atrous_rates=(12, 24, 36), decoder_aspp_dropout=0.1, in_channels=3, classes=1, activation=None,
    )


BUILDERS = {"smp_deeplabv3plus": _build_deeplab}
MISSING_CODE = {
    "unext": "The UNeXt architecture lives in the external repository jeya-maria-jose/UNeXt-pytorch "
             "(archs.py), which Phase I cloned on Colab. That code is not in this repository, so the checkpoint "
             "cannot be instantiated here.",
    "densed_dsaspp": "No notebook or module in this repository defines the DenseDSSPP architecture. "
                     "The checkpoint's key layout is documented, but the model cannot be rebuilt without its source.",
}


def compatibility(path: Path) -> dict:
    """Try a strict load into the matching architecture. Never raises."""
    info = inspect_checkpoint(path)
    result = {"loadable": False, "family": info.get("detected_family"), "diagnostic": None}
    if not info.get("loaded"):
        result["diagnostic"] = info.get("error")
        return result
    family = info.get("detected_family")
    if family is None:
        result["diagnostic"] = "Key layout does not match any known architecture; it was not loaded into a model."
        return result
    if family in MISSING_CODE:
        result["diagnostic"] = MISSING_CODE[family]
        return result
    try:
        _get_model(path, family)
    except ImportError as exc:
        result["diagnostic"] = f"Architecture package not installed ({exc.name or exc}). Install backend/requirements-ml.txt."
        return result
    except Exception as exc:  # strict load mismatch etc.
        result["diagnostic"] = f"Strict load failed: {type(exc).__name__}: {str(exc)[:400]}"
        return result
    result.update(loadable=True, diagnostic="State dict loaded with strict=True (all keys matched).")
    return result


def _get_model(path: Path, family: str):
    key = (str(path), path.stat().st_mtime_ns)
    with _lock:
        if key in _model_cache:
            return _model_cache[key]
    sd, err = _load_state_dict(path)
    if sd is None:
        raise RuntimeError(err)
    model = BUILDERS[family]()
    model.load_state_dict(sd, strict=True)
    model.eval()
    torch, _ = _torch()
    with torch.no_grad():  # warm-up so reported latencies exclude one-time kernel initialisation
        model(torch.zeros(1, 3, 512, 512))
    with _lock:
        _model_cache[key] = model
    return model


_bench_lock = threading.Lock()


def benchmark(path: Path, size: int = 512, runs: int = 3) -> dict:
    """CPU forward-pass latency on a synthetic zero tensor. This measures speed only
    and says nothing about accuracy."""
    compat = compatibility(path)
    if not compat["loadable"]:
        return {"measured": False, "diagnostic": compat["diagnostic"]}
    torch, _ = _torch()
    model = _get_model(path, compat["family"])
    x = torch.zeros(1, 3, size, size)
    times = []
    with _bench_lock, torch.no_grad():
        model(x)  # warm-up
        for _ in range(runs):
            t0 = time.perf_counter()
            model(x)
            times.append(time.perf_counter() - t0)
    return {
        "measured": True,
        "device": "cpu",
        "input_shape": [1, 3, size, size],
        "input": "synthetic zeros (no imagery available)",
        "runs": runs,
        "median_ms": statistics.median(times) * 1000,
        "min_ms": min(times) * 1000,
        "torch_threads": torch.get_num_threads(),
    }
