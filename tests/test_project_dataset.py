"""项目数据集导入与重建测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.errors import Code
from backend.project.dataset import (
    delete_sample,
    import_images,
    import_tree,
    list_samples,
    rebuild_dataset,
)
from backend.project.project import (
    PROJECT_FILE,
    ProjectError,
    create_project,
    load_project,
)
from tests.support.images import build_dataset_tree, make_image

CLASSES = ("水杯", "书本", "笔袋")
CREATED_AT = "2026-11-17T10:00:00+08:00"


def new_project(tmp_path: Path) -> Path:
    root = tmp_path / "学生 项目"
    create_project(
        root,
        project_id="proj-import-0001",
        name="导入测试",
        classes=CLASSES,
        created_at=CREATED_AT,
    )
    return root


def make_source(tmp_path: Path, name: str, count: int = 2) -> Path:
    source = tmp_path / name
    source.mkdir()
    for index in range(count):
        color = (
            (abs(hash(name)) + index * 37) % 256,
            (index * 53 + 11) % 256,
            (abs(hash(name)) // 7 + index * 29) % 256,
        )
        make_image(source / f"照片 {index}.jpg", color)
    return source


def seed_full_tree(root: Path) -> None:
    seed_tree(root, images_per_batch=1)


def seed_tree(root: Path, *, images_per_batch: int) -> None:
    build_dataset_tree(
        root / "data",
        classes=CLASSES,
        train_batches=2,
        images_per_batch=images_per_batch,
    )
    rebuild_dataset(root, dataset_id="ds-import-0001")


def test_import_copies_png_and_reports_incomplete_batches(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = make_source(tmp_path, "手机照片", count=3)

    result = import_images(
        root, class_name="水杯", source_dir=source, batch="batch-1"
    )
    assert result.imported == 3
    assert result.duplicates == 0 and result.invalid == 0
    # 其他类别还没有数据，数据清单按 T03 规则无法生成；文件仍应导入。
    assert result.manifest_path is None
    assert result.manifest_error is not None
    assert "批次" in result.manifest_error

    target = root / "data" / "images" / "水杯" / "batch-1"
    files = sorted(target.glob("*.png"))
    assert len(files) == 3
    assert all(path.suffix == ".png" for path in files)


def test_import_skips_duplicate_content(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = make_source(tmp_path, "手机照片", count=2)

    first = import_images(root, class_name="水杯", source_dir=source, batch="batch-1")
    second = import_images(root, class_name="水杯", source_dir=source, batch="batch-2")
    assert first.imported == 2
    assert second.imported == 0
    assert second.duplicates == 2


def test_import_counts_invalid_images(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = tmp_path / "坏照片"
    source.mkdir()
    make_image(source / "ok.png", (10, 20, 30))
    (source / "not-image.png").write_text("not an image", encoding="utf-8")

    result = import_images(root, class_name="水杯", source_dir=source, batch="batch-1")
    assert result.imported == 1
    assert result.invalid == 1


def test_import_rejects_unknown_class(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = make_source(tmp_path, "照片")
    with pytest.raises(ProjectError) as error:
        import_images(root, class_name="桌子", source_dir=source)
    assert error.value.code is Code.PROJECT_CLASS_INVALID


def test_import_rejects_missing_source(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        import_images(root, class_name="水杯", source_dir=tmp_path / "missing")
    assert error.value.code is Code.PROJECT_IMPORT_INVALID


def test_import_rejects_invalid_batch_name(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = make_source(tmp_path, "照片")
    with pytest.raises(ProjectError) as error:
        import_images(
            root, class_name="水杯", source_dir=source, batch="..\\bad batch"
        )
    assert error.value.code is Code.PROJECT_IMPORT_INVALID


def test_import_default_batch_is_unique(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = make_source(tmp_path, "照片", count=1)
    first = import_images(root, class_name="水杯", source_dir=source)
    second_source = make_source(tmp_path, "照片2", count=1)
    second = import_images(root, class_name="水杯", source_dir=second_source)

    assert first.batch.startswith("batch-")
    assert second.batch.startswith("batch-")
    assert first.target_dir != second.target_dir


def test_import_after_full_dataset_rebuilds_manifest(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    seed_full_tree(root)
    before = len(
        json.loads(
            (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
        )["samples"]
    )

    source = make_source(tmp_path, "新照片", count=2)
    result = import_images(
        root, class_name="书本", source_dir=source, batch="batch-new"
    )
    assert result.imported == 2
    assert result.manifest_path is not None
    assert result.manifest_error is None

    project = load_project(root / PROJECT_FILE)
    assert project.dataset_manifest == "data/dataset-manifest.json"
    manifest = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest["samples"]) == before + 2
    assert manifest["classes"] == list(CLASSES)
    assert result.class_counts["total"] == before + 2


def test_import_test_split_reaches_manifest(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    seed_full_tree(root)
    source = make_source(tmp_path, "测试照片", count=2)

    result = import_images(
        root, class_name="书本", source_dir=source, split="test", batch="batch-test"
    )
    assert result.imported == 2
    assert (root / "data" / "test-images" / "书本" / "batch-test").is_dir()

    manifest = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    test_samples = [item for item in manifest["samples"] if item["split"] == "test"]
    assert len(test_samples) == 5
    assert result.class_counts["splits"]["test"] == 5


def test_rebuild_scans_existing_files(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    build_dataset_tree(
        root / "data", classes=CLASSES, train_batches=2, images_per_batch=1
    )

    manifest_path, manifest = rebuild_dataset(root, dataset_id="ds-manual-0001")
    assert manifest_path.is_file()
    assert manifest_path == root / "data" / "dataset-manifest.json"
    assert manifest["classes"] == list(CLASSES)
    assert len(manifest["samples"]) == 9

    _, again = rebuild_dataset(root, dataset_id="ds-manual-0002")
    assert [item["path"] for item in again["samples"]] == [
        item["path"] for item in manifest["samples"]
    ]


def test_cli_import_and_rebuild(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = new_project(tmp_path)
    seed_full_tree(root)
    source = make_source(tmp_path, "命令行照片", count=1)

    exit_code = main(
        [
            "import",
            "--root",
            str(root),
            "--class",
            "水杯",
            "--source",
            str(source),
            "--batch",
            "batch-cli",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and payload["ok"] is True
    assert payload["imported"] == 1
    assert payload["manifest_path"] is not None

    exit_code = main(["rebuild-dataset", "--root", str(root)])
    rebuilt = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert rebuilt["summary"]["total"] == 10


def test_list_samples_counts(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    seed_full_tree(root)

    payload = list_samples(root)
    assert payload["total"] == 9
    assert payload["classes"] == list(CLASSES)
    # 存储划分：data/images 记为 train、data/test-images 记为 test；验证批次由清单决定。
    assert payload["counts"]["train"] == {name: 2 for name in CLASSES}
    assert payload["counts"]["test"] == {name: 1 for name in CLASSES}
    assert all(
        {"path", "class_name", "split", "capture_batch"} <= set(sample)
        for sample in payload["samples"]
    )


def test_delete_sample_rebuilds_manifest(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    seed_tree(root, images_per_batch=2)
    payload = list_samples(root)
    assert payload["total"] == 15
    target = payload["samples"][0]["path"]

    result = delete_sample(root, path=target)
    assert result["deleted"] == target
    assert result["manifest_path"] is not None
    assert result["manifest_error"] is None
    assert not (root / "data" / target).exists()

    manifest = json.loads(
        (root / "data" / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest["samples"]) == 14


def test_delete_sample_cleans_empty_batch_dir(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    seed_full_tree(root)
    source = make_source(tmp_path, "临时批次", count=1)
    import_images(root, class_name="水杯", source_dir=source, batch="batch-temp")

    payload = list_samples(root)
    row = next(
        sample for sample in payload["samples"] if sample["capture_batch"] == "batch-temp"
    )
    delete_sample(root, path=row["path"])
    assert not (root / "data" / "images" / "水杯" / "batch-temp").exists()


def test_delete_sample_rejects_outside_path(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    with pytest.raises(ProjectError) as error:
        delete_sample(root, path="../project.json")
    assert error.value.code is Code.PROJECT_IMPORT_INVALID


def test_delete_sample_rejects_missing_file(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    seed_full_tree(root)
    with pytest.raises(ProjectError) as error:
        delete_sample(root, path="images/水杯/batch-1/not-there.png")
    assert error.value.code is Code.PROJECT_IMPORT_INVALID


def test_cli_samples_and_delete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = new_project(tmp_path)
    seed_tree(root, images_per_batch=2)

    exit_code = main(["samples", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and payload["total"] == 15

    target = payload["samples"][0]["path"]
    exit_code = main(
        ["delete-sample", "--root", str(root), "--path", target]
    )
    deleted = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and deleted["ok"] is True
    assert deleted["deleted"] == target

    exit_code = main(["samples", "--root", str(root)])
    again = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and again["total"] == 14

def make_tree_source(tmp_path: Path) -> Path:
    source = tmp_path / "课堂 照片"
    for class_index, class_name in enumerate(CLASSES):
        for batch_index in (1, 2):
            folder = source / class_name / f"batch-{batch_index}"
            folder.mkdir(parents=True)
            for index in range(2):
                make_image(
                    folder / f"照片-{index}.jpg",
                    (class_index * 80 + batch_index * 10, index * 60, 90),
                )
    return source


def test_import_tree_imports_class_batches(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = make_tree_source(tmp_path)

    result = import_tree(root, source_dir=source)
    assert result.classes == 3
    assert result.batches == 6
    assert result.imported == 12
    assert result.duplicates == 0 and result.invalid == 0
    assert result.manifest_path is not None
    assert result.class_counts["total"] == 12
    assert {(item.class_name, item.batch) for item in result.items} == {
        (name, f"batch-{batch}") for name in CLASSES for batch in (1, 2)
    }


def test_import_tree_overrides_batch_and_handles_flat_class(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = tmp_path / "平铺照片" / CLASSES[0]
    source.mkdir(parents=True)
    make_image(source / "a.jpg", (10, 20, 30))
    make_image(source / "b.jpg", (40, 50, 60))

    result = import_tree(root, source_dir=source.parent, batch="batch-flat")
    assert result.classes == 1 and result.batches == 1
    assert result.imported == 2
    assert result.items[0].batch == "batch-flat"


def test_import_tree_rejects_unknown_class(tmp_path: Path) -> None:
    root = new_project(tmp_path)
    source = tmp_path / "错误照片"
    folder = source / "不存在类别" / "batch-1"
    folder.mkdir(parents=True)
    make_image(folder / "a.jpg", (1, 2, 3))

    with pytest.raises(ProjectError) as error:
        import_tree(root, source_dir=source)
    assert error.value.code == Code.PROJECT_CLASS_INVALID


def test_cli_import_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.project.cli import main

    root = new_project(tmp_path)
    source = make_tree_source(tmp_path)

    exit_code = main(["import-tree", "--root", str(root), "--source", str(source)])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0 and payload["ok"] is True
    assert payload["imported"] == 12
    assert len(payload["items"]) == 6
    assert payload["manifest_path"] is not None