"""Segmentation lab: dataset split reproduction, metrics, error states, and (optionally) real inference."""

import importlib.util
import random

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.services.lab import confusion


def test_confusion_metrics_exact():
    pred = np.array([[1, 1, 0, 0]], dtype=bool)
    gt = np.array([[1, 0, 1, 0]], dtype=bool)
    m = confusion(pred, gt)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["iou"] == pytest.approx(1 / 3) and m["dice"] == pytest.approx(0.5)
    assert m["precision"] == 0.5 and m["recall"] == 0.5
    empty = confusion(np.zeros((2, 2), bool), np.zeros((2, 2), bool))
    assert empty["iou"] is None and empty["precision"] is None  # undefined, never reported as 0 or 1


@pytest.fixture()
def lab_client(tmp_path, monkeypatch):
    from app import config, registry
    from app.main import create_app

    root = tmp_path / "deepgloberoad"
    (root / "train").mkdir(parents=True)
    (root / "valid").mkdir()
    for i in range(10):
        Image.fromarray(np.full((8, 8, 3), i * 20, np.uint8)).save(root / "train" / f"{100 + i}_sat.jpg")
        Image.fromarray((np.eye(8) * 255).astype(np.uint8)).convert("RGB").save(root / "train" / f"{100 + i}_mask.png")
    Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(root / "valid" / "900_sat.jpg")
    ck = tmp_path / "checkpoints-x" / "checkpoints"
    ck.mkdir(parents=True)
    (ck / "best_road_model_fake.pth").write_bytes(b"not a checkpoint")
    monkeypatch.setenv("ROUTERESILIENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROUTERESILIENCE_CACHE_DIR", str(tmp_path / "cache"))
    config.get_settings.cache_clear()
    registry.reset_for_tests(config.get_settings())
    from app.services import lab
    lab._dataset.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    config.get_settings.cache_clear()
    lab._dataset.cache_clear()
    registry._registry = None


def test_split_reproduces_phase1(lab_client):
    ids = sorted(str(100 + i) for i in range(10))
    random.seed(42)
    random.shuffle(ids)
    expected_val = set(ids[8:])
    r = lab_client.get("/api/lab/samples?subset=phase1_val").json()
    assert {s["image_id"] for s in r["items"]} == expected_val
    assert r["dataset"]["phase1_train"] == 8 and r["dataset"]["phase1_val"] == 2
    allr = lab_client.get("/api/lab/samples?subset=all").json()
    assert allr["total"] == 11
    v = next(s for s in allr["items"] if s["image_id"] == "900")
    assert v["has_ground_truth"] is False and v["phase1_subset"] is None


def test_lab_errors(lab_client):
    assert lab_client.get("/api/lab/images/900/gt").status_code == 404
    assert lab_client.get("/api/lab/images/900/sat").headers["content-type"] == "image/jpeg"
    assert lab_client.get("/api/lab/images/..%2F..%2Fx/sat").status_code in (400, 404)
    r = lab_client.post("/api/lab/infer", json={"model_id": "fake", "image_id": "100"})
    assert r.status_code == 409 and r.json()["code"] == "checkpoint_incompatible"
    assert lab_client.post("/api/lab/infer", json={"model_id": "nope", "image_id": "100"}).json()["code"] == "model_missing"
    assert lab_client.post("/api/lab/infer", json={"model_id": "fake", "image_id": "999"}).json()["code"] == "sample_missing"
    assert lab_client.get("/api/lab/results/0123456789ab/mask.png").json()["code"] == "result_missing"
    models = lab_client.get("/api/lab/models").json()
    assert models[0]["loadable"] is False and models[0]["diagnostic"]


def test_dataset_missing(tmp_path, monkeypatch):
    from app import config, registry
    from app.main import create_app
    from app.services import lab

    monkeypatch.setenv("ROUTERESILIENCE_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    registry.reset_for_tests(config.get_settings())
    try:
        with TestClient(create_app()) as c:
            assert c.get("/api/lab/samples").json()["code"] == "dataset_missing"
    finally:
        config.get_settings.cache_clear()
        lab._dataset.cache_clear()
        registry._registry = None


@pytest.mark.skipif(importlib.util.find_spec("segmentation_models_pytorch") is None, reason="optional ML dependencies not installed")
def test_real_inference_matches_phase1_mask():
    from app import config, registry
    from app.services import lab

    config.get_settings.cache_clear()
    registry._registry = None
    lab._dataset.cache_clear()
    reg = registry.get_registry()
    if "deeplabv3" not in reg.checkpoints or not reg.mask_sets.get("deeplab"):
        pytest.skip("real checkpoint / Phase I masks not present")
    try:
        lab.dataset()
    except lab.LabError:
        pytest.skip("DeepGlobe dataset not present")
    r = lab.infer("deeplabv3", "109889")
    assert r["phase1_subset"] == "val" and r["metrics"]["evaluation"].startswith("held-out")
    assert r["phase1_agreement"]["iou_with_saved_mask"] > 0.9  # same model + preprocessing as the notebook
    assert 0 <= r["metrics"]["iou"] <= 1
