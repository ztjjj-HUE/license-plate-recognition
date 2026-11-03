# 基于 Zynq-7010 的嵌入式车牌识别与显示系统

在 Xilinx Zynq-7010（XC7Z010CLG400-1）上实现的端侧车牌识别与本地显示系统。
摄像头采集 800×480 图像，经颜色定位与轻量卷积网络识别车牌，结果一路直写帧缓冲
经 HDMI 本地呈现，一路经以太网推送到上位机留档，全程不依赖 PC 算力。

## 系统概览

| 项目 | 指标 |
| --- | --- |
| 主控平台 | Zynq-7010，双核 Cortex-A9 + 可编程逻辑 |
| 图像采集 | OV5640，DVP 并行接口，800×480 |
| 识别模型 | Caffe 轻量卷积网络，约 2.44 M 参数，20 时间步 × 84 类，CTC 解码 |
| 本地显示 | 1920×1080 自绘界面，点阵图集渲染中文 |
| 定位耗时 | 软件版 22~32 ms；PL 加速器实测 4.5 ms |
| 端到端帧率 | 14~18 fps |
| 识别准确率 | 100 张样本整体 71.0%（正对 86.7%） |
| 定位加速器 | 7 个 DSP48E1、5 925 LUT、162 Kb BRAM |

## 目录结构

```
01_板端与PC工程/
  software/board/     板端主程序：采集、定位、识别、渲染、网络推送
  shared/             板端与上位机共用的协议与图像打包
  pc_viewer/          上位机：实时预览、记录、统计、CSV 导出
  models/             Caffe 网络定义与模型
02_板端脚本/           板端启动脚本与识别服务入口
03_定位加速器_RTL/     核心模块源码 + 全量 RTL 压缩包（164 个文件）
docs/                  项目报告
```

## 快速开始

### 板端（Zynq-7010 / Linux）

```bash
cd 01_板端与PC工程
python3 -m software.board.blue_tcp_server \
        --bind 169.254.72.156 --camera /dev/video0 \
        --camera-backend ov5640 --hdmi-fb /dev/fb1
```

依赖：Python 3、OpenCV、NumPy。模型通过 `cv2.dnn.readNetFromCaffe` 加载。

### 上位机（Windows）

```bash
cd 01_板端与PC工程/pc_viewer
python launch.py
```

依赖：Python 3、Tkinter、Pillow。

## 说明

- 识别模型来自开源项目 HyperLPR，遵循其原始许可证（见 `models/hyperlpr_caffe/LICENSE`）。
- `03_定位加速器_RTL` 中的核心模块为综合后网表的结构化还原，用于资源统计与
  模块划分分析，未做与原始网表的形式等价验证；完整 164 个文件见同目录压缩包。
- 项目报告见 `docs/`。
