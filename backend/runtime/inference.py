"""从模型产物包加载并执行推理。

运行时只依赖模型包、ONNX Runtime 与 Pillow：标签、预处理、后处理全部从
``manifest.json`` 读取，不访问训练目录、训练脚本或训练框架。预处理实现必须与
导出时记录的步骤一致，输入张量摘要比对用于发现两端实现漂移。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import onnxruntime as ort
from PIL import Image

from ..contracts import paths
from ..contracts.errors import Code

MANIFEST_NAME = "manifest.json"
_PIL_INTERPOLATION = {
    "nearest": Image.NEAREST,
    "bilinear": Image.BILINEAR,
    "bicubic": Image.BICUBIC,
    "area": Image.BOX,
}


class RuntimeInferenceError(Exception):
    """推理无法继续。``code`` 是稳定错误码。"""

    def __init__(self, code: Code, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Prediction:
    class_id: int
    label: str
    probability: float


@dataclass(frozen=True)
class PredictionResult:
    artifact_id: str
    predictions: tuple[Prediction, ...]
    raw_output: tuple[float, ...]
    input_shape: tuple[int, ...]


class ManifestPreprocessor:
    """按 manifest 中有序步骤执行预处理。

    当前支持 ``resize(stretch)``、``normalize``、``transpose``、
    ``add_batch_dimension``；letterbox/crop 与 0..1 像素输入显式拒绝，
    不能静默用近似参数代替。
    """

    def __init__(self, preprocessing: dict[str, Any]) -> None:
        self._steps = preprocessing["steps"]
        self._pixel_range = tuple(preprocessing["source_pixel_range"])

    def __call__(self, image: Image.Image) -> np.ndarray:
        if image.mode != "RGB":
            image = image.convert("RGB")
        if self._pixel_range != (0, 255):
            raise RuntimeInferenceError(
                Code.RUNTIME_PREPROCESSING_UNSUPPORTED,
                f"运行时仅支持 0..255 像素输入，清单声明 {list(self._pixel_range)}",
            )

        data: Image.Image | np.ndarray = image
        for step in self._steps:
            op = step["op"]
            if op == "resize":
                data = self._resize(data, step)
            elif op == "normalize":
                data = self._normalize(data, step)
            elif op == "transpose":
                data = self._transpose(data, step)
            elif op == "add_batch_dimension":
                data = self._add_batch(data, step)
            else:  # pragma: no cover - Schema 已限制取值
                raise RuntimeInferenceError(
                    Code.RUNTIME_PREPROCESSING_UNSUPPORTED, f"不支持的预处理步骤 {op!r}"
                )

        if isinstance(data, Image.Image):
            raise RuntimeInferenceError(
                Code.RUNTIME_PREPROCESSING_UNSUPPORTED,
                "预处理未产生张量，缺少 normalize 或 transpose 步骤",
            )
        return np.ascontiguousarray(data, dtype=np.float32)

    def _resize(self, data: Image.Image | np.ndarray, step: dict[str, Any]) -> Image.Image:
        if not isinstance(data, Image.Image):
            raise RuntimeInferenceError(
                Code.RUNTIME_PREPROCESSING_UNSUPPORTED,
                "缩放必须位于归一化之前",
            )
        if step["mode"] != "stretch":
            raise RuntimeInferenceError(
                Code.RUNTIME_PREPROCESSING_UNSUPPORTED,
                f"运行时尚未实现 {step['mode']!r} 缩放，仅支持 stretch",
            )
        return data.resize(
            (int(step["width"]), int(step["height"])),
            _PIL_INTERPOLATION[step["interpolation"]],
        )

    def _normalize(
        self, data: Image.Image | np.ndarray, step: dict[str, Any]
    ) -> np.ndarray:
        if isinstance(data, Image.Image):
            array = np.asarray(data, dtype=np.float32)
        else:
            array = np.asarray(data, dtype=np.float32)
        if step["channel_order"] == "BGR":
            array = array[:, :, ::-1]
        elif step["channel_order"] != "RGB":
            raise RuntimeInferenceError(
                Code.RUNTIME_PREPROCESSING_UNSUPPORTED,
                f"运行时仅支持 RGB/BGR 归一化，清单声明 {step['channel_order']!r}",
            )
        mean = np.asarray(step["mean"], dtype=np.float32)
        std = np.asarray(step["std"], dtype=np.float32)
        return (array * float(step["scale"]) - mean) / std

    def _transpose(self, data: Image.Image | np.ndarray, step: dict[str, Any]) -> np.ndarray:
        if isinstance(data, Image.Image):
            raise RuntimeInferenceError(
                Code.RUNTIME_PREPROCESSING_UNSUPPORTED, "转置必须位于归一化之后"
            )
        if step["from"] != "HWC" or step["to"] != "CHW":
            raise RuntimeInferenceError(
                Code.RUNTIME_PREPROCESSING_UNSUPPORTED,
                f"运行时仅支持 HWC→CHW，清单声明 {step['from']}→{step['to']}",
            )
        return np.transpose(data, (2, 0, 1))

    def _add_batch(self, data: Image.Image | np.ndarray, step: dict[str, Any]) -> np.ndarray:
        if isinstance(data, Image.Image):
            raise RuntimeInferenceError(
                Code.RUNTIME_PREPROCESSING_UNSUPPORTED, "批次维必须在张量上添加"
            )
        return np.expand_dims(data, axis=int(step["axis"]))


def load_image(path: str | Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            image.load()
            return image.convert("RGB")
    except (OSError, ValueError) as error:
        raise RuntimeInferenceError(
            Code.RUNTIME_IMAGE_INVALID, f"无法解码图片 {path}：{error}"
        ) from error


def _default_session_factory(model_path: Path) -> ort.InferenceSession:
    try:
        return ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
    except Exception as error:  # onnxruntime 异常类型不固定
        raise RuntimeInferenceError(
            Code.RUNTIME_MODEL_LOAD_FAILED, f"ONNX Runtime 无法加载模型：{error}"
        ) from error


class ModelPackageRuntime:
    """已加载的模型产物包。"""

    def __init__(
        self,
        *,
        package_dir: Path,
        manifest: dict[str, Any],
        labels: Sequence[str],
        preprocessor: ManifestPreprocessor,
        session: ort.InferenceSession,
        input_name: str,
        output_name: str,
        output_meaning: str,
        class_axis: int,
        postprocessing: Sequence[dict[str, Any]],
    ) -> None:
        self.package_dir = package_dir
        self.manifest = manifest
        self.labels = list(labels)
        self.artifact_id = str(manifest["artifact_id"])
        self._preprocessor = preprocessor
        self._session = session
        self._input_name = input_name
        self._output_name = output_name
        self._output_meaning = output_meaning
        self._class_axis = class_axis
        self._postprocessing = list(postprocessing)

    @classmethod
    def load(
        cls,
        package_dir: str | Path,
        *,
        session_factory: Callable[[Path], ort.InferenceSession] | None = None,
    ) -> "ModelPackageRuntime":
        package = Path(package_dir)
        manifest_path = package / MANIFEST_NAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeInferenceError(
                Code.RUNTIME_MODEL_LOAD_FAILED,
                f"无法读取 {manifest_path}：{error}",
            ) from error

        model_path = paths.resolve_in_package(package, manifest["model"]["path"])
        if model_path is None or not model_path.is_file():
            raise RuntimeInferenceError(
                Code.RUNTIME_MODEL_LOAD_FAILED,
                f"模型文件 {manifest['model']['path']} 不存在或越出产物包",
            )
        labels_path = paths.resolve_in_package(package, manifest["labels"]["path"])
        if labels_path is None or not labels_path.is_file():
            raise RuntimeInferenceError(
                Code.RUNTIME_MODEL_LOAD_FAILED,
                f"标签文件 {manifest['labels']['path']} 不存在或越出产物包",
            )
        try:
            labels = json.loads(labels_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeInferenceError(
                Code.RUNTIME_MODEL_LOAD_FAILED, f"无法读取标签文件：{error}"
            ) from error
        if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
            raise RuntimeInferenceError(
                Code.RUNTIME_MODEL_LOAD_FAILED, "标签文件必须是字符串数组"
            )

        factory = session_factory or _default_session_factory
        session = factory(model_path)
        inputs = session.get_inputs()
        outputs = session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise RuntimeInferenceError(
                Code.RUNTIME_OUTPUT_INVALID,
                f"运行时仅支持单输入单输出模型，实际 {len(inputs)} / {len(outputs)}",
            )
        declared_input = manifest["inputs"][0]
        declared_output = manifest["outputs"][0]
        if inputs[0].name != declared_input["name"]:
            raise RuntimeInferenceError(
                Code.RUNTIME_OUTPUT_INVALID,
                f"模型输入名 {inputs[0].name!r} 与清单 {declared_input['name']!r} 不一致",
            )
        if outputs[0].name != declared_output["name"]:
            raise RuntimeInferenceError(
                Code.RUNTIME_OUTPUT_INVALID,
                f"模型输出名 {outputs[0].name!r} 与清单 {declared_output['name']!r} 不一致",
            )
        if str(inputs[0].type) != "tensor(float)":
            raise RuntimeInferenceError(
                Code.RUNTIME_OUTPUT_INVALID,
                f"运行时仅支持 float32 输入，模型输入类型为 {inputs[0].type}",
            )

        return cls(
            package_dir=package,
            manifest=manifest,
            labels=labels,
            preprocessor=ManifestPreprocessor(manifest["preprocessing"]),
            session=session,
            input_name=inputs[0].name,
            output_name=outputs[0].name,
            output_meaning=str(declared_output["meaning"]),
            class_axis=int(declared_output.get("class_axis", -1)),
            postprocessing=manifest["postprocessing"]["steps"],
        )

    def predict_image(self, image: Image.Image) -> PredictionResult:
        tensor = self._preprocessor(image)
        raw = self._session.run([self._output_name], {self._input_name: tensor})[0]
        array = np.asarray(raw, dtype=np.float32)
        probabilities = self._postprocess(array)
        order = np.argsort(-probabilities)
        predictions = tuple(
            Prediction(
                class_id=int(index),
                label=self.labels[int(index)],
                probability=float(probabilities[int(index)]),
            )
            for index in order
        )
        return PredictionResult(
            artifact_id=self.artifact_id,
            predictions=predictions,
            raw_output=tuple(float(value) for value in array.reshape(-1)),
            input_shape=tuple(int(value) for value in tensor.shape),
        )

    def predict_file(self, image_path: str | Path) -> PredictionResult:
        return self.predict_image(load_image(image_path))

    def preprocess_file(self, image_path: str | Path) -> np.ndarray:
        """按 manifest 预处理，供输入一致性检查使用。"""
        return self._preprocessor(load_image(image_path))

    def _postprocess(self, raw: np.ndarray) -> np.ndarray:
        array = raw
        if array.ndim == 1:
            array = array[None, :]
        if self._output_meaning == "class_probabilities":
            return array.reshape(-1)
        for step in self._postprocessing:
            if step["op"] != "softmax":  # pragma: no cover - Schema 限制
                raise RuntimeInferenceError(
                    Code.RUNTIME_OUTPUT_INVALID, f"不支持的输出后处理 {step['op']!r}"
                )
            axis = int(step["axis"]) % array.ndim
            shifted = array - np.max(array, axis=axis, keepdims=True)
            exponential = np.exp(shifted)
            array = exponential / np.sum(exponential, axis=axis, keepdims=True)
        return array.reshape(-1)
