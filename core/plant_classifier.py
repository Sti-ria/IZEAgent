import json
from pathlib import Path

import cv2
import numpy as np


DEFAULT_IMAGE_SIZE = (64, 64)


def imread_unicode(path):
    """
    支持中文路径的图片读取。
    Windows 下 cv2.imread 遇到中文路径有时会失败，所以用 np.fromfile + cv2.imdecode。
    """
    path = str(path)
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img


def create_hog_descriptor(image_size=DEFAULT_IMAGE_SIZE):
    """
    创建 HOG 特征提取器，用于提取形状信息。
    """
    win_size = image_size
    block_size = (16, 16)
    block_stride = (8, 8)
    cell_size = (8, 8)
    nbins = 9

    return cv2.HOGDescriptor(
        win_size,
        block_size,
        block_stride,
        cell_size,
        nbins,
    )


def extract_features(image, image_size=DEFAULT_IMAGE_SIZE):
    """
    从一个格子图片中提取特征。

    特征包含：
    1. HSV 颜色直方图：区分不同植物颜色
    2. HSV 小缩略图：保留大致空间布局
    3. HOG：保留植物轮廓形状

    输入：
        image: BGR 格式图片

    输出：
        一维 float32 特征向量
    """
    if image is None or image.size == 0:
        raise ValueError("Empty image passed to extract_features")

    resized = cv2.resize(image, image_size)

    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)

    # 1. HSV 颜色直方图
    hist = cv2.calcHist(
        [hsv],
        [0, 1, 2],
        None,
        [16, 8, 8],
        [0, 180, 0, 256, 0, 256],
    )
    cv2.normalize(hist, hist)
    hist = hist.flatten().astype(np.float32)

    # 2. HSV 缩略图
    thumb = cv2.resize(hsv, (16, 16)).astype(np.float32)
    thumb[:, :, 0] /= 180.0
    thumb[:, :, 1] /= 255.0
    thumb[:, :, 2] /= 255.0
    thumb = thumb.flatten()

    # 3. HOG 形状特征
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    hog = create_hog_descriptor(image_size)
    hog_feat = hog.compute(gray)

    if hog_feat is None:
        hog_feat = np.zeros((1,), dtype=np.float32)
    else:
        hog_feat = hog_feat.flatten().astype(np.float32)

    hog_norm = np.linalg.norm(hog_feat) + 1e-6
    hog_feat = hog_feat / hog_norm

    feature = np.concatenate([hist, thumb, hog_feat]).astype(np.float32)

    return feature


class PlantClassifier:
    """
    植物格子分类器。

    这个分类器使用保存好的 KNN 特征库。
    训练脚本会生成：
        models/plant_cell_classifier.npz
    """

    def __init__(
        self,
        model_path="models/plant_cell_classifier.npz",
        unknown_threshold=0.55,
        k=5,
    ):
        self.model_path = Path(model_path)
        self.unknown_threshold = unknown_threshold
        self.k = k

        self.features = None
        self.labels = None
        self.mean = None
        self.std = None
        self.class_names = None
        self.image_size = DEFAULT_IMAGE_SIZE

        self.load()

    def load(self):
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Plant classifier model not found: {self.model_path}\n"
                f"Please run: python .\\tools\\train_plant_classifier.py"
            )

        data = np.load(self.model_path, allow_pickle=True)

        self.features = data["features"].astype(np.float32)
        self.labels = data["labels"].astype(np.int32)
        self.mean = data["mean"].astype(np.float32)
        self.std = data["std"].astype(np.float32)
        self.class_names = data["class_names"].tolist()

        if "image_size" in data:
            size = data["image_size"].astype(np.int32).tolist()
            self.image_size = (int(size[0]), int(size[1]))

        if "k" in data:
            self.k = int(data["k"][0])

        print("Loaded plant classifier:")
        print(f"- model: {self.model_path}")
        print(f"- classes: {self.class_names}")
        print(f"- samples: {len(self.labels)}")
        print(f"- k: {self.k}")
        print(f"- unknown_threshold: {self.unknown_threshold}")

    def predict(self, image):
        """
        预测单个格子。

        返回：
        {
            "label": "sunflower" / "empty" / "unknown",
            "confidence": 0.87,
            "raw_label": "sunflower"
        }
        """
        if image is None or image.size == 0:
            return {
                "label": "unknown",
                "confidence": 0.0,
                "raw_label": "unknown",
            }

        feature = extract_features(image, self.image_size)
        feature = (feature - self.mean) / self.std

        diff = self.features - feature.reshape(1, -1)
        distances = np.sqrt(np.sum(diff * diff, axis=1))

        k = min(self.k, len(distances))
        nearest_idx = np.argpartition(distances, k - 1)[:k]

        label_scores = {}

        for idx in nearest_idx:
            label_id = int(self.labels[idx])
            dist = float(distances[idx])

            # 距离越小，权重越大
            weight = 1.0 / (dist + 1e-6)
            label_scores[label_id] = label_scores.get(label_id, 0.0) + weight

        total_score = sum(label_scores.values())

        best_label_id = max(label_scores, key=label_scores.get)
        best_score = label_scores[best_label_id]
        confidence = best_score / total_score if total_score > 0 else 0.0

        raw_label = self.class_names[best_label_id]

        if confidence < self.unknown_threshold:
            final_label = "unknown"
        else:
            final_label = raw_label

        return {
            "label": final_label,
            "confidence": float(confidence),
            "raw_label": raw_label,
        }
