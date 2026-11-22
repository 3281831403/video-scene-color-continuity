# video-scene-color-continuity

## 题面

同一场戏剪成三段后，观众一眼就看出中间那段偏绿：现有实现统计每个镜头的 RGB 均值时不排除过曝像素，高光把色温估计拉偏；挑参考镜头时直接拿第一个，而不是色温取中位数的那个，整场戏跟着一起偏；算白平衡增益时把绿通道也乘上增益，画面整体亮度漂移；红蓝增益写反了，通道顺序错位让偏色更明显；增益被当成 sRGB 编码值直接相乘，校正量变成非线性；跨镜头色差用 RGB 欧氏距离且不做归一，分数随镜头亮度忽大忽小；镜头边界渐变的 t 不做钳制，端点之外继续外推；validate 只看色温范围、不看增益乘积是否约等于 1，曝光不守恒也无人报错；批量处理时第二个场景复用第一个场景的参考镜头，场景之间互相污染；apply_gains 对已经钳制的像素继续相乘，过曝边界凭空多出一条硬边。colorcont/continuous.py 是核心，tests/test_continuous.py 15个红。要修的是：修复上述 10 个缺陷，只改 colorcont/continuous.py，让 15 条测试全部通过。

## 数据模型与契约

- 像素 `[r, g, b]`，帧 `list[list[像素]]`，镜头 `list[帧]`，场景 `list[镜头]`，批量为 `list[场景]`。
- 所有采样都是线性光浮点，范围 `0.0..1.0`；本仓库不做 sRGB 编解码，增益必须乘在线性值上。
- 色温单位为开尔文 K，中性值 `NEUTRAL_K = 6500.0`，合法区间 `[TEMP_MIN, TEMP_MAX] = [2000.0, 12000.0]`。
- 浮点比较容差 `ATOL = 1e-9`；增益乘积容差 `GAIN_PRODUCT_TOL = 0.01`。
- 过曝阈值 `CLIP_LEVEL = 0.98`，输出上限 `CLIP_CEILING = 1.0`；常量与 8 个函数同住 `colorcont/continuous.py`，测试从那里导入。

`colorcont/continuous.py` 里的 8 个公开函数目前全部是 `raise NotImplementedError` 桩，函数契约写在 docstring 里，验收标准写在测试里；逐个实现即可。

## 运行方式

在仓库根目录执行：

```powershell
python -m pytest tests -q
```

初始状态必须恰好 `15 failed`，并且不能出现 collection、import 或 syntax error。全部实现正确后应变成 `15 passed`；如果仍有失败，失败项应当只来自尚未实现的桩。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 游戏、图形与多媒体 |
| 子方向 | 音视频处理 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

## 约束

- 只用 Python 标准库（`math`）与 `pytest`，离线运行，不使用随机数。
- `tests/test_continuous.py` 不可修改：15 条测试是唯一验收标准。
- 修复只允许落在 `colorcont/continuous.py`。
