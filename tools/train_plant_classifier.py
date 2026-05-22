import sys
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from core.plant_classifier import extract_features, imread_unicode, DEFAULT_IMAGE_SIZE


DATA_DIR = ROOT_DIR / "assets" / "plants_labeled"
MODEL_DIR = ROOT_DIR / "models"
MODEL_PATH = MODEL_DIR / "plant_cell_classifier.npz"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

IMAGE_SIZE = DEFAULT_IMAGE_SIZE
VAL_RATIO = 0.2
K = 5
RANDOM_SEED = 42


def augment_image(img):
    """
    只做轻微增强，不做左右翻转。

    原因：
    PVZ 植物朝向是有意义的，左右翻转可能制造不存在的样本。
    """
    results = []

    results.append(img)

    # 亮一点
    results.append(cv2.convertScaleAbs(img, alpha=1.08, beta=8))

    # 暗一点
    results.append(cv2.convertScaleAbs(img, alpha=0.92, beta=-8))

    # 轻微模糊
    results.append(cv2.GaussianBlur(img, (3, 3), 0))

    return results


def collect_dataset():
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Dataset folder not found: {DATA_DIR}")

    class_dirs = [
        p for p in DATA_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ]

    class_dirs = sorted(class_dirs, key=lambda p: p.name.lower())

    if not class_dirs:
        raise RuntimeError(f"No class folders found in: {DATA_DIR}")

    class_names = []
    samples_by_class = {}

    for class_dir in class_dirs:
        image_paths = [
            p for p in class_dir.rglob("*")
            if p.suffix.lower() in IMAGE_EXTS
        ]

        if not image_paths:
            print(f"[WARN] Skip empty class folder: {class_dir.name}")
            continue

        class_names.append(class_dir.name)
        samples_by_class[class_dir.name] = image_paths

    if not class_names:
        raise RuntimeError("No valid image samples found.")

    return class_names, samples_by_class


def split_train_val(samples_by_class):
    rng = np.random.default_rng(RANDOM_SEED)

    train_items = []
    val_items = []

    for label_name, paths in samples_by_class.items():
        paths = list(paths)
        rng.shuffle(paths)

        if len(paths) >= 5:
            val_count = max(1, int(len(paths) * VAL_RATIO))
        else:
            val_count = 0

        val_paths = paths[:val_count]
        train_paths = paths[val_count:]

        if not train_paths:
            train_paths = paths
            val_paths = []

        for p in train_paths:
            train_items.append((p, label_name))

        for p in val_paths:
            val_items.append((p, label_name))

    return train_items, val_items


def build_features(items, class_to_id, use_augmentation):
    features = []
    labels = []

    for img_path, label_name in items:
        img = imread_unicode(img_path)

        if img is None:
            print(f"[WARN] Failed to read image: {img_path}")
            continue

        images = augment_image(img) if use_augmentation else [img]

        for one_img in images:
            try:
                feat = extract_features(one_img, IMAGE_SIZE)
            except Exception as e:
                print(f"[WARN] Failed to extract feature from {img_path}: {e}")
                continue

            features.append(feat)
            labels.append(class_to_id[label_name])

    if not features:
        raise RuntimeError("No features were extracted.")

    features = np.asarray(features, dtype=np.float32)
    labels = np.asarray(labels, dtype=np.int32)

    return features, labels


def predict_with_arrays(train_features, train_labels, feature, k):
    diff = train_features - feature.reshape(1, -1)
    distances = np.sqrt(np.sum(diff * diff, axis=1))

    k = min(k, len(distances))
    nearest_idx = np.argpartition(distances, k - 1)[:k]

    label_scores = {}

    for idx in nearest_idx:
        label_id = int(train_labels[idx])
        dist = float(distances[idx])
        weight = 1.0 / (dist + 1e-6)
        label_scores[label_id] = label_scores.get(label_id, 0.0) + weight

    best_label_id = max(label_scores, key=label_scores.get)
    return best_label_id


def evaluate(train_features, train_labels, val_features, val_labels, class_names):
    if val_features is None or len(val_features) == 0:
        print("\nNo validation set. Skip evaluation.")
        return

    total = len(val_labels)
    correct = 0

    per_class_total = defaultdict(int)
    per_class_correct = defaultdict(int)

    confusion = np.zeros((len(class_names), len(class_names)), dtype=np.int32)

    for feature, true_label in zip(val_features, val_labels):
        pred_label = predict_with_arrays(
            train_features,
            train_labels,
            feature,
            K,
        )

        true_label = int(true_label)
        pred_label = int(pred_label)

        confusion[true_label, pred_label] += 1

        per_class_total[true_label] += 1

        if pred_label == true_label:
            correct += 1
            per_class_correct[true_label] += 1

    acc = correct / total if total > 0 else 0.0

    print("\nValidation result:")
    print(f"- total: {total}")
    print(f"- correct: {correct}")
    print(f"- accuracy: {acc:.3f}")

    print("\nPer-class accuracy:")
    for class_id, class_name in enumerate(class_names):
        t = per_class_total[class_id]
        c = per_class_correct[class_id]

        if t == 0:
            print(f"- {class_name}: no validation samples")
        else:
            print(f"- {class_name}: {c}/{t} = {c / t:.3f}")

    print("\nConfusion matrix:")
    print("Rows = true label, columns = predicted label")
    print("Class order:")
    for i, name in enumerate(class_names):
        print(f"{i}: {name}")

    print(confusion)


def main():
    print("Collecting dataset...")
    print(f"Dataset dir: {DATA_DIR}")

    class_names, samples_by_class = collect_dataset()

    print("\nClasses found:")
    for name in class_names:
        print(f"- {name}: {len(samples_by_class[name])} images")

    if "empty" not in class_names:
        print("\n[WARN] You do not have an 'empty' class.")
        print("Please create: assets/plants_labeled/empty")

    class_to_id = {
        name: idx
        for idx, name in enumerate(class_names)
    }

    train_items, val_items = split_train_val(samples_by_class)

    print("\nSplit:")
    print(f"- train original images: {len(train_items)}")
    print(f"- val images: {len(val_items)}")

    print("\nExtracting train features...")
    train_features_raw, train_labels = build_features(
        train_items,
        class_to_id,
        use_augmentation=True,
    )

    print("Extracting validation features...")
    if val_items:
        val_features_raw, val_labels = build_features(
            val_items,
            class_to_id,
            use_augmentation=False,
        )
    else:
        val_features_raw = None
        val_labels = None

    mean = train_features_raw.mean(axis=0)
    std = train_features_raw.std(axis=0) + 1e-6

    train_features = (train_features_raw - mean) / std

    if val_features_raw is not None:
        val_features = (val_features_raw - mean) / std
    else:
        val_features = None

    evaluate(
        train_features,
        train_labels,
        val_features,
        val_labels,
        class_names,
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    np.savez_compressed(
        MODEL_PATH,
        features=train_features.astype(np.float32),
        labels=train_labels.astype(np.int32),
        mean=mean.astype(np.float32),
        std=std.astype(np.float32),
        class_names=np.asarray(class_names),
        image_size=np.asarray(IMAGE_SIZE, dtype=np.int32),
        k=np.asarray([K], dtype=np.int32),
    )

    print("\nModel saved:")
    print(MODEL_PATH)


if __name__ == "__main__":
    main()
