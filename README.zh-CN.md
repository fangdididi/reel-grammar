# Reel Grammar（剪辑语法卡）

[English](README.md) · **简体中文**

**借一支视频的节奏和观感，不借它的素材。**

Reel Grammar 是一个专门应对"照这支视频做一个"这类需求的 Agent 技能。它测量参考片的剪辑语法，整理成一张由数字组成的小小"语法卡"，
用清晰的判定和改法逐版对照草稿，并在交付前做一次撞片检查，确保新片既不复用参考片的画面，也不照描它的剪辑表。

适用于 Claude Code、Codex、Cursor，以及任何能读 `SKILL.md`、能运行 Python 脚本的 Agent。它本身不生成视频，
而是指导和检查你已经在用的制作工具。

## 为什么需要它

参考片代表的是一种用户说不出口的感觉。没有测量，Agent 要么完全抓不住节奏，要么只会照搬表面。Reel Grammar 给这种感觉一组
可以瞄准、可以讨论的数字：

- "你的镜头平均 2.6 秒，参考片平均 1.2 秒。"
- "参考片在最后三分之一越剪越快，你的一直是匀速。"
- "参考片 85% 是硬切、只有一次黑场；你的处处都是叠化。"

## 功能

- **镜头与衔接识别。** 硬切、叠化、黑场过渡、闪白；夹在两刀之间的短黑场会算作衔接，而不是一个镜头。
- **节奏。** 镜头时长的平均值、中位数、第 10 和第 90 百分位，六档时长分布，每分钟刀数，以及把全片切成十段的节奏曲线，
  并标注平稳、越来越快或越来越慢。
- **观感。** 亮度、对比度、饱和度、冷暖、接近纯黑的画面占比，以及五色主色板，整片和每个镜头都有。
- **运动。** 每个镜头标为静止、轻微或激烈，并用相位相关法识别横向镜头运动（横摇、俯仰、手持晃动）。
- **对照报告。** 十一项检查，每项 ON、CLOSE 或 OFF，总分 100，并列出最先要改的三件事。只要有 OFF 退出码就是 1，可以直接放进流水线把关。
- **撞片检查。** 每个镜头取三帧做感知哈希，找出复用的画面（ECHO）和高度相似的画面（LOOKALIKE）；序列比对找出照描的剪辑表
  （TIMING_TRACE）；主色板完全相同会被标出（PALETTE_CLONE）。
- **联系表。** 每个镜头中间取一帧并标注，给只能靠眼睛判断的部分用。
- **输出不含素材。** 语法 JSON 里只有数字和色值，可以放心保存和分享。
- **纯本地运行。** 不联网，不上传。

## 环境要求

- Python 3.9 或更高版本，装有 `numpy`
- PATH 里有 `ffmpeg` 和 `ffprobe`
- `Pillow`（可选，只有 `sheet` 命令需要）

## 安装

把仓库克隆到你所用 Agent 的技能目录。

**Claude Code**

```bash
git clone https://github.com/fangdididi/reel-grammar ~/.claude/skills/reel-grammar
```

**Codex**

```bash
git clone https://github.com/fangdididi/reel-grammar ~/.codex/skills/reel-grammar
```

**Cursor**（项目规则或技能目录）

```bash
git clone https://github.com/fangdididi/reel-grammar .cursor/skills/reel-grammar
```

**其他 Agent**：把文件夹放在 Agent 能读到的位置，并让它读取 `SKILL.md`。

如有需要，安装 Python 依赖：

```bash
pip install numpy pillow
```

## 使用方法

直接对 Agent 说类似"这是参考片，把我们的发布视频做成这种感觉"，它就会按 `SKILL.md` 的流程走。你也可以自己运行脚本：

```bash
# 1. 测量参考片
python3 scripts/reelgrammar.py read reference.mp4 --out ref
python3 scripts/reelgrammar.py sheet reference.mp4 --out ref/sheet.png

# 2. 拿草稿和保存的语法对照
python3 scripts/reelgrammar.py match draft.mp4 --grammar ref/grammar.json --out check

# 3. 确认没有搬运原片
python3 scripts/reelgrammar.py copycheck draft.mp4 reference.mp4
```

参数调节：`--hard`（默认 0.30）是硬切阈值，越低找到的剪切点越多；`--soft`（默认 0.30）用于叠化和淡入淡出；
`--fps`（默认 10）是分析时的采样帧率。

## 输出示例

```text
# Match: draft.mp4 against reference.mp4

Score 68/100. ON 6, CLOSE 3, OFF 2.

| check | reference | draft | verdict | what to change |
|---|---|---|---|---|
| shot length (mean) | 1.07 s | 1.9 s | OFF | cut shots to about 1.1 s on average (now 1.9 s) |
| pacing shape | speeds_up | steady (r=0.12) | OFF | the reference speeds up; yours steady. Move cuts so the busy slices line up |
| saturation | 0.61 | 0.52 | CLOSE | raise saturation toward 0.61 (now 0.52) |
| ... | | | | |

## First three changes

1. cut shots to about 1.1 s on average (now 1.9 s)
2. the reference speeds up; yours steady. Move cuts so the busy slices line up
3. raise saturation toward 0.61 (now 0.52)
```

报告本身是英文的，含义分别是：平均镜头时长偏长要剪短、参考片越剪越快而草稿是匀速、饱和度偏低要提高。

## 文件结构

```text
reel-grammar/
├── SKILL.md               # 技能说明（英文）
├── SKILL.zh-CN.md         # 技能说明（中文）
├── README.md              # 英文说明
├── README.zh-CN.md        # 本文件
├── LICENSE
├── scripts/
│   └── reelgrammar.py     # read、match、copycheck、sheet 四个命令
└── tests/
    ├── make_clips.py      # 生成剪切点已知的合成测试片段
    └── test_reelgrammar.py
```

## 测试

```bash
python3 -m unittest discover -s tests
```

测试会渲染一批剪切时间、叠化、黑场、闪白、横摇都已知的合成片段，然后检查测量结果、对照判定、撞片检查和命令行退出码。

## 局限

- 不测推拉和变焦，请对照联系表目测记录。
- 快速闪光和频闪特效可能被当作剪切点；两个非常相似的镜头之间的硬切可能漏检。调整 `--hard` 并查看联系表。
- 撞片检查比对的是画面和时长，是一张安全网，不是法律意见。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
