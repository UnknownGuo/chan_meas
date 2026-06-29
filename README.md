# chan_meas — V2V 信道测量处理与分析平台

博士科研项目，针对 **28 GHz V2V（车对车）**无线信道的测量数据处理。覆盖从原始 `.bin` 帧到可交互分析仪表盘的完整流水线：

```
原始 .bin
  └─ LFM 匹配滤波 → CIR
       └─ B2B 频域校准
            └─ 自适应 SAGE / 频域 MUSIC 多径提取
                 └─ FastAPI 分析仪表盘 + Module B 信道统计
```

---

## 功能亮点

| 模块 | 功能 |
|------|------|
| **IO** | 解析自研硬件 `.bin` 帧，提取 IQ + GPS |
| **匹配滤波** | LFM chirp 匹配滤波，GPU 加速（PyTorch CUDA） |
| **B2B 校准** | Wiener/Tikhonov 正则化频域逆滤波，去除系统响应 |
| **自适应 SAGE** | 覆盖度驱动终止（95% 能量），无需手动设路径数 |
| **频域 MUSIC** | 前向-后向空间平滑 + MDL 自动定阶，输出时延估计 |
| **仪表盘** | FastAPI + 地图瓦片代理 + 实时后台分析任务 |
| **Module B** | 路径损耗拟合、阴影衰落、多径衰落（K 因子、Nakagami 等） |

---

## 目录结构

```
chan_meas/
├── config/
│   ├── local.example.py   # 路径配置模板（提交 git）
│   └── local.py           # 本机路径（不提交 git）
├── data/
│   ├── calibration/b2b/   # B2B 校准矩阵（.mat / .npy）
│   ├── tile_cache/        # 地图瓦片本地缓存
│   └── ui_samples/        # 导出的前端 JSON 数据集
├── docs/                  # 设计文档、规格说明
├── notebooks/             # 探索性分析 Jupyter Notebook
├── scripts/               # 工具脚本
├── src/
│   ├── io/
│   │   └── bin_read.py            # .bin 帧解析 + LFM 匹配滤波
│   ├── calibration/
│   │   ├── b2b_frequency.py       # 频域 B2B 校准
│   │   ├── cfo_estimator.py       # 载波频偏（CFO）估计
│   │   └── constants.py           # 校准常数（衰减量、正则化系数）
│   ├── signal/
│   │   ├── delay_doppler_sage.py  # 标准 SAGE（时延-多普勒）
│   │   ├── sage_adaptive.py       # 自适应 SAGE（覆盖度终止）
│   │   └── music_delay.py         # 频域 MUSIC 时延估计
│   ├── pipeline/
│   │   └── analyze.py             # 单文件分析流水线（Web UI 调用入口）
│   ├── analysis/
│   │   └── module_b.py            # Module B：信道统计分析
│   ├── ui_dataset.py              # CIR → JSON 数据打包
│   └── frontend_app.py            # FastAPI Web 仪表盘
└── web/                           # 前端静态资源（HTML/JS/CSS）
```

> **架构原则**：算子层（`src/signal/`）→ 标定层（`src/calibration/`）→ 流水线层（`src/pipeline/`）。所有路径只在 `src/paths.py` 中定义，其他文件不硬编码路径。

---

## 快速开始

### 1. 配置本机路径

```bash
cp config/local.example.py config/local.py
# 编辑 local.py，填入原始数据目录路径
```

### 2. 安装依赖

```bash
pip install torch numpy scipy fastapi uvicorn pydantic matplotlib
```

主要依赖版本参考：

| 包 | 版本 |
|----|------|
| torch | ≥ 2.8 |
| numpy | ≥ 2.4 |
| scipy | ≥ 1.17 |
| fastapi | ≥ 0.100 |
| uvicorn | ≥ 0.44 |

### 3. 启动分析仪表盘

```bash
uvicorn src.frontend_app:app --reload --host 0.0.0.0 --port 8000
```

浏览器访问 `http://localhost:8000`，加载已导出的 JSON 数据集即可查看 CIR 瀑布图、Doppler-Delay 谱图、多径径迹等。

### 4. 从 .bin 导出数据集（命令行）

```bash
python -m src.ui_dataset \
  --rx /path/to/rx.bin \
  --out data/ui_samples/my_measurement.json \
  --joint          # 同时运行联合时延-多普勒估计
```

---

## 核心算法

### LFM 匹配滤波（`src/io/bin_read.py`）

发射信号为线性调频序列 $s[n] = e^{j\pi n^2/U}$，接收端做 FFT 域匹配滤波得到 CIR：

$$h[\tau] = \text{IFFT}\bigl(\text{FFT}(r \cdot \times 3) \cdot S^*_\text{MF}\bigr)[\text{central } U \text{ taps}]$$

三倍 tiling 避免循环卷积混叠，CUDA 加速。

### B2B 频域校准（`src/calibration/b2b_frequency.py`）

Wiener/Tikhonov 正则化逆滤波去除系统脉冲响应：

$$H_\text{cal}(f) = \frac{H_\text{meas}(f) \cdot H^*_\text{b2b}(f)}{|H_\text{b2b}(f)|^2 + \lambda}$$

$\lambda$ 相对于 $\max|H_\text{b2b}|^2$ 自适应，避免低功率频点放大噪声。

### 自适应 SAGE（`src/signal/sage_adaptive.py`）

单天线时延-多普勒 SAGE，以重建 PDP 能量覆盖度为终止条件：

$$\text{coverage} = \frac{\sum_\tau |\hat{s}_\text{sum}[\tau]|^2}{\sum_\tau |x[\tau]|^2} \geq \text{target}$$

不依赖固定路径数，自动适配每个慢时间窗口的散射复杂度。

### 频域 MUSIC（`src/signal/music_delay.py`）

前向-后向空间平滑协方差 + MDL 自动定阶 + 伪谱扫描：

$$P_\text{MUSIC}(\tau) = \frac{1}{\|E_n^H \mathbf{a}(\tau)\|^2}$$

时延分辨率超越 FFT，峰值功率从实际 PDP 读取（伪谱高度无物理意义）。

---

## 数据说明

三类测量数据：

| 类型 | 用途 |
|------|------|
| **B2B**（背靠背线缆直连） | 提取硬件系统脉冲响应，用于频域校准 |
| **静态 OTA** | 估计硬件载波频偏（CFO），用于帧间相位对齐 |
| **V2V 动态** | 目标数据，车载运动场景信道 |

硬件对每 15 个序列做平均后输出，原始动态范围约 20 dB。

---

## 已知问题 / 开发状态

- [x] 数据管理框架
- [x] LFM 匹配滤波 + GPU 加速
- [x] B2B 频域校准
- [x] 自适应 SAGE 多径提取
- [x] 频域 MUSIC 时延估计
- [x] FastAPI 仪表盘 + Module B 信道统计
- [ ] 静态 OTA CFO 补偿（帧间相位对齐）
- [ ] 旧 MATLAB 代码完整迁移

---

## 引用 / 参考

如果本代码对你的研究有帮助，请引用（BibTeX 待补充）。
