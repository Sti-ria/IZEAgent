# PVZAgent

PVZAgent 是一个面向《植物大战僵尸》我是僵尸无尽（I, Zombie, Endless / IZE）模式的计算机视觉项目。项目目前主要用于识别游戏窗口中的棋盘、植物阵型和 IZE 主题，并提供棋盘调试、训练数据采集、植物分类模型训练等工具，方便后续继续接入策略决策和自动操作。

本 README 主要用于项目交接，帮助队友快速了解仓库结构、各文件作用、调试入口和运行方式。

---

## 1. 当前项目状态

目前主要完成的工作包括：

* 自动查找 PVZ 游戏窗口，并获取游戏客户区截图；
* 根据配置好的棋盘参数，将游戏画面切分为 5 行 × 9 列棋盘格；
* 使用训练好的植物格子分类器识别每个格子的植物类别；
* 使用棋盘记忆机制提高连续帧识别稳定性；
* 支持暂停菜单、窗口遮挡、异常截图等情况下冻结识别，避免误更新棋盘；
* 支持 IZE 无尽新一关检测，并重新初始化棋盘记忆；
* 根据前 5 列初始阵型识别 IZE 主题；
* 根据主题先验修正部分容易混淆的植物识别结果，例如豌豆射手和双发射手；
* 提供训练集裁剪、植物分类器训练、窗口检测、资源清单生成等辅助脚本。

当前主要调试入口是：

```bash
python .\tools\debug_board_recognition.py
```

`main.py` 是早期自动操作入口，目前实际调试中基本没有使用，可以保留作为后续接入自动放僵尸逻辑的参考。

---

## 2. 运行环境

项目主要依赖 Windows 环境，因为窗口查找和客户区坐标获取使用了 Windows API / `win32gui`。

建议环境：

* Windows 10 / Windows 11
* Python 3.9 或以上
* 已打开《Plants vs. Zombies》游戏窗口
* 游戏窗口大小尽量保持和 `config/settings.yaml` 中棋盘参数匹配

安装依赖：

```bash
pip install -r requirements.txt
```

如果运行时报 `win32gui` 或 `win32con` 相关错误，需要额外安装：

```bash
pip install pywin32
```

建议后续将下面这一行补充到 `requirements.txt`：

```text
pywin32
```

---

## 3. 推荐运行方式

### 3.1 调试棋盘识别和主题识别

这是当前项目最主要、最推荐使用的入口。

```bash
python .\tools\debug_board_recognition.py
```

运行后脚本会：

1. 读取 `config/settings.yaml`；
2. 如果存在 `config/local_settings.yaml`，会用本地配置覆盖默认配置；
3. 自动查找 PVZ 窗口；
4. 截取游戏客户区画面；
5. 调用 `BoardRecognizer` 识别棋盘；
6. 调用 `ThemeRecognizer` 和 `StableThemeRecognizer` 识别并锁定 IZE 主题；
7. 调用 `ThemeBoardCorrector` 根据主题修正部分识别结果；
8. 用 OpenCV 窗口显示调试画面。

快捷键：

```text
Q / ESC：退出调试窗口
R      ：重置已锁定主题
```

调试窗口中每个格子会显示：

```text
M：memory label，棋盘记忆中的最终标签
L：live label，当前帧分类器识别结果
R：raw label，KNN 原始最近类别
E：empty 连续确认帧数
V：空地视觉检查结果
```

---

### 3.2 采集植物格子训练样本

```bash
python .\tools\extract_plant_cells.py
```

该脚本用于从当前 PVZ 游戏画面中裁剪棋盘格子，生成训练样本或辅助标注数据。

运行后会：

1. 自动查找 PVZ 窗口；
2. 尝试识别并点击暂停菜单中的 `Resume Game`；
3. 截取完整游戏画面；
4. 根据 `settings.yaml` 中的棋盘参数绘制网格预览；
5. 在 OpenCV 窗口中按 `S` 保存当前棋盘格子；
6. 将裁剪结果保存到：

```text
assets/templates/plants_raw/batch_时间戳/
```

同时会生成：

```text
assets/templates/grid_preview.png
assets/templates/pvz_full_frame.png
assets/templates/resume_detection_debug.png
```

这些图片主要用于确认棋盘参数是否正确，以及检查自动恢复游戏的识别是否正常。

---

### 3.3 训练植物分类模型

```bash
python .\tools\train_plant_classifier.py
```

训练脚本会读取：

```text
assets/plants_labeled/
```

该目录下每个子文件夹代表一个类别，例如：

```text
chomper/
empty/
fumeshroom/
kernelpult/
magnetshroom/
peashooter/
potatomine/
puffshroom/
repeater/
scaredyshroom/
snowpea/
spikeweed/
splitpea/
squash/
starfruit/
sunflower/
threepeater/
torchwood/
umbrellaleaf/
wallnut/
```

每个类别文件夹中保存该植物或空地的格子截图，例如：

```text
spikeweed_001.png
spikeweed_002.png
spikeweed_003.png
...
```

训练完成后会生成模型文件：

```text
models/plant_cell_classifier.npz
```

该模型会被 `core/plant_classifier.py` 和 `core/board_recognizer.py` 使用。

---

### 3.4 测试窗口识别

```bash
python .\test_window.py
```

该脚本会枚举当前所有可见窗口，打印窗口句柄和标题。用于调试 `settings.yaml` 中的窗口标题关键字是否能匹配到 PVZ。

---

### 3.5 早期自动操作入口

```bash
python .\main.py
```

`main.py` 是早期保留下来的自动操作入口，包含窗口查找、截图、棋盘识别、卡牌识别、策略选择和鼠标点击控制逻辑。

不过目前调试主要不走这个文件。当前更完整、更稳定的识别链路在：

```text
core/board_recognizer.py
core/theme_recognizer.py
core/board_corrector.py
utils/debug_view.py
```

以及入口：

```text
tools/debug_board_recognition.py
```

因此交接时建议优先阅读和使用 `tools/debug_board_recognition.py`。

---

## 4. 仓库结构说明

当前仓库大致结构如下：

```text
PVZAgent/
├─ assets/
│  ├─ plants_labeled/
│  ├─ templates/
│  └─ plants_labeled.zip
├─ config/
│  ├─ settings.yaml
│  └─ theme_signatures.yaml
├─ core/
│  ├─ board_corrector.py
│  ├─ board_debug.py
│  ├─ board_recognizer.py
│  ├─ capture.py
│  ├─ card_detector.py
│  ├─ controller.py
│  ├─ decision.py
│  ├─ game_state.py
│  ├─ grid.py
│  ├─ plant_classifier.py
│  ├─ plant_detector.py
│  ├─ theme_recognizer.py
│  └─ window_finder.py
├─ models/
│  └─ plant_cell_classifier.npz
├─ tools/
│  ├─ debug_board_recognition.py
│  ├─ extract_plant_cells.py
│  ├─ picture_name.py
│  └─ train_plant_classifier.py
├─ utils/
│  └─ debug_view.py
├─ zombieImages/
├─ asset_category_summary.csv
├─ asset_manifest.csv
├─ asset_manifest_categorized.csv
├─ main.py
├─ particles_names.txt
├─ README.md
├─ reanim_names.txt
├─ requirements.txt
├─ test_window.py
└─ zombieImages.zip
```

---

## 5. 目录和文件功能说明

### 5.1 `config/`

#### `config/settings.yaml`

项目主配置文件，包含窗口匹配、截图调试、棋盘坐标、卡槽位置、棋盘记忆、帧有效性检查、植物分类器、主题识别和棋盘修正规则等配置。

重要配置包括：

```yaml
window:
  title_keywords:
    - "Plants vs. Zombies"
```

用于自动查找 PVZ 窗口。

```yaml
grid:
  rows: 5
  cols: 9
  board_left: 30
  board_top: 80
  board_width: 735
  board_height: 500
  crop_padding_ratio: 0.08
```

用于定义棋盘区域和格子裁剪方式。窗口可以自动捕捉，但棋盘格子的坐标参数是人工调好的，所以如果游戏窗口大小或缩放发生变化，需要重新调整这些参数。

```yaml
plant_classifier:
  model_path: models/plant_cell_classifier.npz
  unknown_threshold: 0.55
  k: 5
```

用于配置植物分类模型路径和 KNN 参数。

```yaml
theme:
  enabled: true
  signatures_path: config/theme_signatures.yaml
  max_col: 4
```

用于配置 IZE 主题识别。`max_col: 4` 表示只看前 5 列，也就是 `c0-c4`。

```yaml
board_corrector:
  enabled: true
  signatures_path: config/theme_signatures.yaml
  max_col: 4
```

用于根据已锁定主题修正部分容易混淆的植物。

---

#### `config/theme_signatures.yaml`

IZE 主题签名配置文件。

文件中定义了不同主题下前 5 列植物的可重集统计。例如：

```yaml
themes:
  综合:
    support_total: 8
    signature_total: 17
    plants:
      kernelpult: 1
      peashooter: 1
      snowpea: 1
      ...
```

主题识别时会统计前 5 列植物数量，并和这里配置的主题签名进行匹配。

目前支持的主题包括：

```text
综合
控制
即死
输出
爆炸
倾斜
穿刺
回复
```

其中：

```yaml
ignore_for_theme:
  - empty
  - unknown
  - invalid_frame
```

这些标签不会用于主题签名匹配。

```yaml
support_plants:
  - sunflower
  - puffshroom
```

这些植物作为辅助植物统计，不直接作为大多数主题的核心签名植物。

---

### 5.2 `core/`

`core/` 是项目核心逻辑目录。

#### `core/window_finder.py`

负责自动寻找 PVZ 游戏窗口。

主要功能：

* 根据窗口标题关键字查找窗口；
* 如果窗口最小化，则尝试恢复；
* 将窗口置前；
* 获取窗口客户区在屏幕上的绝对坐标。

后续截图和点击都基于客户区坐标，不包含标题栏和边框。

---

#### `core/capture.py`

负责截取 PVZ 客户区画面。

主要类：

```python
PVZCapture
```

主要功能：

* 根据客户区坐标初始化截图区域；
* 窗口移动后更新截图区域；
* 使用 `mss` 截屏，并将 BGRA 转为 OpenCV 使用的 BGR 格式。

---

#### `core/grid.py`

负责管理棋盘网格坐标。

主要类和函数：

```python
PVZGrid
get_grid_config
get_grid_bboxes
crop_cell
crop_grid_cells_for_recognition
```

主要功能：

* 根据 `settings.yaml` 中的棋盘参数计算 5×9 格子位置；
* 获取单个格子的矩形区域和中心点；
* 将点击坐标转换为格子行列；
* 按格子裁剪图像，供植物识别模型使用。

---

#### `core/plant_classifier.py`

植物格子分类器。

该模块使用训练好的 KNN 特征库进行分类。

特征包括：

1. HSV 颜色直方图，用于区分植物颜色；
2. HSV 小缩略图，用于保留大致空间布局；
3. HOG 特征，用于保留植物轮廓形状。

主要类和函数：

```python
PlantClassifier
extract_features
imread_unicode
create_hog_descriptor
```

模型文件路径：

```text
models/plant_cell_classifier.npz
```

预测输出示例：

```python
{
    "label": "sunflower",
    "confidence": 0.87,
    "raw_label": "sunflower"
}
```

如果置信度低于阈值，则最终标签会被置为 `unknown`。

---

#### `core/board_recognizer.py`

当前棋盘识别的核心模块。

主要类：

```python
BoardRecognizer
```

核心目标：

* 只在有效游戏画面上初始化和更新棋盘记忆；
* 暂停菜单、选项菜单、最小化、异常截图时冻结识别；
* 初始化后不允许 `plant -> another plant`；
* 只允许 `plant -> empty`；
* `plant -> empty` 必须连续多帧确认；
* `plant -> empty` 还必须通过空地视觉检查，避免被子弹、僵尸、菜单遮挡时误删植物；
* IZE 无尽进入新一关时自动重置棋盘记忆。

输出包括：

```python
cell_results, board = board_recognizer.recognize(frame)
```

其中 `cell_results` 是每个格子的详细识别信息，`board` 是当前棋盘记忆结果。

---

#### `core/board_debug.py`

棋盘识别结果可视化模块。

主要函数：

```python
draw_board_results(frame, cell_results, show_confidence=True)
```

会在截图上绘制每个格子的识别结果，包括：

* memory label；
* live label；
* raw label；
* empty streak；
* 空地视觉检查；
* 异常帧状态。

这是 `tools/debug_board_recognition.py` 调试窗口中主要使用的绘制函数。

---

#### `core/theme_recognizer.py`

IZE 主题识别模块。

主要类：

```python
ThemeRecognizer
StableThemeRecognizer
```

核心思路：

1. 只统计 IZE 初始植物区域，即 5 行 × 前 5 列 = 25 格；
2. 忽略 `empty`、`unknown`、`invalid_frame`；
3. 将 `sunflower`、`puffshroom` 作为 support plants；
4. 用 `Counter` 统计植物可重集；
5. 与 `theme_signatures.yaml` 中的主题签名计算距离；
6. 连续多帧稳定后锁定主题。

---

#### `core/board_corrector.py`

基于主题先验的棋盘纠错模块。

主要类：

```python
ThemeBoardCorrector
```

当前主要用于修正豌豆射手和双发射手这类容易混淆的情况。

例如：

```yaml
rules:
  综合:
    repeater: peashooter

  输出:
    peashooter: repeater

  控制:
    peashooter: repeater
```

纠错范围只看 IZE 初始化区域，即前 5 列 `c0-c4`。

---

#### `core/card_detector.py`

僵尸卡槽检测模块。

主要类：

```python
CardDetector
```

主要功能：

* 根据 `settings.yaml` 中的卡槽配置计算每张僵尸卡牌位置；
* 裁剪卡槽区域；
* 根据亮度和灰度标准差判断卡牌是否可用。

目前这是较简单的经验规则，主要服务于早期自动操作逻辑。

---

#### `core/controller.py`

PVZ 鼠标控制模块。

主要类：

```python
PVZController
```

主要功能：

* 将 PVZ 客户区内部坐标转换为屏幕绝对坐标；
* 点击卡牌；
* 点击棋盘格；
* 执行放置僵尸动作；
* 在暂停、退出或紧急停止时释放鼠标和键盘状态。

目前主要供 `main.py` 早期自动操作入口使用。

---

#### `core/decision.py`

早期策略规划模块。

主要类：

```python
IZombieDecisionMaker
```

第一版策略逻辑：

* 统计每一行植物强度；
* 选择防守最弱的一行；
* 根据该行强度选择僵尸卡牌。

该模块目前仍比较简单，主要作为后续自动决策扩展的起点。

---

#### `core/game_state.py`

游戏状态缓存模块。

主要类：

```python
GameState
```

用于保存当前识别到的棋盘、卡牌和阳光数量。

目前功能较轻，主要用于早期 `main.py` 自动操作链路。

---

#### `core/plant_detector.py`

早期模板匹配版植物识别模块。

主要类：

```python
PlantDetector
```

第一版识别策略：

* 对每个格子裁剪 cell image；
* 和 `assets/templates/plants` 中的模板做 `cv2.matchTemplate`；
* 选择分数最高且超过阈值的植物。

当前主要识别链路已经转向 `BoardRecognizer + PlantClassifier`，所以该文件可以视为早期版本或备用方案。

---

### 5.3 `tools/`

`tools/` 存放调试、数据采集、训练和资源处理脚本。

#### `tools/debug_board_recognition.py`

当前最重要的调试入口。

主要功能：

* 加载配置；
* 查找 PVZ 窗口；
* 检测窗口是否被遮挡；
* 截取游戏客户区；
* 调用 `BoardRecognizer` 识别棋盘；
* 调用 `ThemeRecognizer` 识别主题；
* 多帧稳定后锁定主题；
* 根据主题调用 `ThemeBoardCorrector` 修正棋盘；
* 在 OpenCV 窗口中显示调试信息。

推荐优先阅读这个文件，因为它串起了当前项目最完整的识别流程。

---

#### `tools/extract_plant_cells.py`

训练样本采集工具。

主要功能：

* 自动查找 PVZ 窗口；
* 截取 PVZ 游戏画面；
* 根据棋盘参数绘制网格预览；
* 按 `S` 后裁剪前 5 列格子；
* 保存到 `assets/templates/plants_raw/batch_时间戳/`。

该脚本适合用于制作或扩充 `assets/plants_labeled/` 训练集。

---

#### `tools/train_plant_classifier.py`

植物分类模型训练脚本。

主要流程：

1. 读取 `assets/plants_labeled/` 下的分类数据；
2. 按类别收集图片；
3. 划分训练集和验证集；
4. 对训练图片做轻微增强，包括变亮、变暗、轻微模糊；
5. 提取 HSV 直方图、HSV 缩略图、HOG 特征；
6. 标准化特征；
7. 使用 KNN 思路保存训练特征库；
8. 输出验证集准确率和混淆矩阵；
9. 保存模型到 `models/plant_cell_classifier.npz`。

---

#### `tools/picture_name.py`

游戏解包素材目录扫描工具。

主要功能：

* 遍历 `zombieImages/` 下的图片文件；
* 读取每张图片的宽、高、通道数和透明通道信息；
* 生成 `asset_manifest.csv`。

目前该脚本和游戏素材解包相关，当前棋盘识别流程暂时用不到。

---

### 5.4 `utils/`

#### `utils/debug_view.py`

早期调试视图模块。

主要类：

```python
DebugView
```

主要用于 `main.py` 中绘制棋盘格和卡槽可用状态。

当前主调试入口 `tools/debug_board_recognition.py` 使用的是 `core/board_debug.py` 中的可视化逻辑，因此 `debug_view.py` 更偏早期自动操作链路。

---

### 5.5 `assets/`

#### `assets/plants_labeled/`

植物分类模型训练集。

目录结构是：

```text
assets/plants_labeled/
├─ chomper/
├─ empty/
├─ fumeshroom/
├─ kernelpult/
├─ magnetshroom/
├─ peashooter/
├─ potatomine/
├─ puffshroom/
├─ repeater/
├─ scaredyshroom/
├─ snowpea/
├─ spikeweed/
├─ splitpea/
├─ squash/
├─ starfruit/
├─ sunflower/
├─ threepeater/
├─ torchwood/
├─ umbrellaleaf/
└─ wallnut/
```

每个子文件夹是一个类别，里面是对应类别的格子截图。该目录是 `tools/train_plant_classifier.py` 的输入数据。

---

#### `assets/templates/`

主要存放数据采集和调试过程中生成的图片。

常见内容：

```text
assets/templates/plants_raw/
assets/templates/grid_preview.png
assets/templates/pvz_full_frame.png
assets/templates/resume_detection_debug.png
```

其中：

* `plants_raw/`：由 `extract_plant_cells.py` 裁剪出的原始格子样本；
* `grid_preview.png`：棋盘网格预览图；
* `pvz_full_frame.png`：完整 PVZ 截图；
* `resume_detection_debug.png`：暂停菜单 Resume Game 识别调试图。

---

### 5.6 `models/`

#### `models/plant_cell_classifier.npz`

植物格子分类模型文件。

由下面命令生成：

```bash
python .\tools\train_plant_classifier.py
```

被下面模块加载：

```text
core/plant_classifier.py
core/board_recognizer.py
```

如果缺少该文件，运行棋盘识别时会报错，并提示先运行训练脚本。

---

### 5.7 游戏解包素材相关文件

以下内容来自游戏素材解包，目前对当前棋盘识别主流程不是必须的：

```text
zombieImages/
zombieImages.zip
asset_manifest.csv
asset_manifest_categorized.csv
asset_category_summary.csv
particles_names.txt
reanim_names.txt
```

其中 `zombieImages/` 是队友整理的 PVZ 游戏内图片素材包解包结果。当前识别流程主要依赖实时截图和训练集，不直接使用这些素材。

---

## 6. 当前主流程说明

当前推荐的识别调试流程是：

```text
打开 PVZ 游戏
        │
        ▼
运行 tools/debug_board_recognition.py
        │
        ▼
查找 PVZ 窗口并获取客户区坐标
        │
        ▼
截图当前游戏画面
        │
        ▼
根据 settings.yaml 中的 grid 参数裁剪 5×9 棋盘格
        │
        ▼
PlantClassifier 对每个格子分类
        │
        ▼
BoardRecognizer 更新棋盘记忆
        │
        ▼
ThemeRecognizer 根据前 5 列识别 IZE 主题
        │
        ▼
StableThemeRecognizer 多帧稳定后锁定主题
        │
        ▼
ThemeBoardCorrector 根据主题修正识别结果
        │
        ▼
OpenCV 调试窗口显示识别结果
```

---

## 7. 棋盘识别机制说明

### 7.1 棋盘记忆

`BoardRecognizer` 不直接相信单帧识别结果，而是维护一个 `board_memory`。

原因是 PVZ 中会出现：

* 僵尸遮挡植物；
* 子弹遮挡格子；
* 暂停菜单遮挡棋盘；
* 游戏窗口被其他窗口盖住；
* 截图瞬间异常；
* 植物被吃掉时需要确认。

因此识别逻辑采用：

```text
初始化阶段：多帧投票确定初始棋盘
稳定阶段：不允许 plant -> another plant
消失判断：只允许 plant -> empty，并且必须连续多帧确认
异常画面：冻结识别，不更新 memory
新一关：检测到大量不一致后重置 memory
```

### 7.2 空地视觉检查

植物被吃掉后，格子会变为空地。但如果只是被僵尸、子弹、菜单遮挡，不能误判为空地。

因此项目增加了空地视觉检查，主要看：

* 边缘密度；
* 高亮比例；
* 中性灰比例。

只有当分类器认为是 `empty`，并且视觉上也像干净空地时，才会累计 empty streak。

### 7.3 新关卡检测

IZE 无尽每进入新一关时，红线左侧植物会重置。由于一关内部不允许 `empty -> plant`，所以需要单独检测新关卡。

当前逻辑是：

* 只检查红线左侧前几列；
* 只相信高置信度植物；
* 如果连续多帧发现大量 live 结果和 memory 不一致，就认为进入新一关；
* 调用 `reset_memory()` 重新初始化棋盘。

---

## 8. 主题识别和纠错说明

### 8.1 主题识别

IZE 主题识别只统计前 5 列，即：

```text
5 行 × 5 列 = 25 格
```

主题配置在：

```text
config/theme_signatures.yaml
```

识别时会统计植物可重集，并和每个主题的签名计算距离。多帧连续稳定后才锁定主题，避免单帧误判。

### 8.2 主题纠错

有些植物外观相似，分类器容易混淆，例如：

```text
peashooter / repeater
```

因此在主题锁定后，可以根据主题先验纠正结果。例如某个主题中理论上应该出现 repeater，但识别成了 peashooter，就可以按规则修正。

纠错配置在：

```text
config/settings.yaml
```

对应字段：

```yaml
board_corrector:
  rules:
    综合:
      repeater: peashooter

    输出:
      peashooter: repeater

    控制:
      peashooter: repeater
```

---

## 9. 常见问题

### 9.1 找不到 PVZ 窗口

检查：

1. 游戏是否已经打开；
2. 游戏窗口标题是否包含 `Plants vs. Zombies`；
3. `config/settings.yaml` 中的配置是否正确：

```yaml
window:
  title_keywords:
    - "Plants vs. Zombies"
```

也可以运行：

```bash
python .\test_window.py
```

查看当前系统中的窗口标题。

---

### 9.2 棋盘格子位置不对

窗口可以自动捕捉，但棋盘区域参数是人工调好的。如果游戏窗口大小、缩放、分辨率发生变化，可能需要重新调整：

```yaml
grid:
  board_left: 30
  board_top: 80
  board_width: 735
  board_height: 500
```

可以运行：

```bash
python .\tools\extract_plant_cells.py
```

查看 `grid_preview.png`，根据网格预览图调整参数。

---

### 9.3 缺少模型文件

如果出现类似错误：

```text
Plant classifier model not found: models/plant_cell_classifier.npz
```

说明还没有训练模型，运行：

```bash
python .\tools\train_plant_classifier.py
```

---

### 9.4 中文路径读取图片失败

项目中部分图片读取和保存使用了 `np.fromfile + cv2.imdecode` 或 `cv2.imencode + tofile`，是为了兼容 Windows 中文路径下 `cv2.imread` / `cv2.imwrite` 可能失败的问题。

---

### 9.5 暂停菜单或其他窗口遮挡导致识别异常

`tools/debug_board_recognition.py` 和 `BoardRecognizer` 中已经加入了窗口遮挡检测和菜单覆盖检测。

当检测到异常时，识别会冻结，不会更新棋盘记忆。

---

## 10. 后续可继续完善的方向

后续如果继续开发，可以考虑：

1. 将 `debug_board_recognition.py` 中的新识别链路接回 `main.py`；
2. 统一旧版 `PlantDetector` 和新版 `BoardRecognizer` 的数据结构；
3. 完善 `decision.py` 中的 IZE 策略逻辑；
4. 接入更精确的僵尸卡牌识别；
5. 将主题识别、棋盘纠错和自动操作整合成完整 agent；
6. 给 `requirements.txt` 补充 `pywin32`；
7. 增加 `config/local_settings.yaml.example`，方便不同电脑单独配置棋盘坐标；
8. 增加更多训练样本，提高植物分类器泛化能力；
9. 对 `assets/` 和 `zombieImages/` 等大文件目录做 `.gitignore` 或压缩包管理；
10. 将调试图片、原始裁剪样本和模型文件区分为“源码必需”和“可再生成文件”。

---

## 11. 推荐阅读顺序

队友接手时建议按下面顺序阅读：

```text
1. config/settings.yaml
2. tools/debug_board_recognition.py
3. core/board_recognizer.py
4. core/plant_classifier.py
5. core/theme_recognizer.py
6. core/board_corrector.py
7. core/grid.py
8. tools/train_plant_classifier.py
9. tools/extract_plant_cells.py
10. main.py
```

其中前 6 个文件是理解当前识别调试主流程的关键。

---

## 12. 简短交接说明

当前项目的核心不是 `main.py`，而是 `tools/debug_board_recognition.py` 这条调试链路。

当前最重要的成果是：

```text
PVZ 窗口截图
→ 棋盘格子裁剪
→ KNN 植物分类
→ 棋盘记忆稳定识别
→ IZE 主题识别
→ 主题先验纠错
→ OpenCV 可视化调试
```

`main.py` 中的自动点击和策略逻辑目前可以作为后续扩展方向，不建议作为当前主要入口。
