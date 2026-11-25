# DSH Code Film

面向 DeepSeek 的代码驱动 3D 动画制作 Skill，包含场景构建、分镜、镜头与运动编排，以及 Windows 本机渲染与导出流程。

中文 · [English](#english)

[Skill 源码](skills/code-film-render/) · [引擎源码](engine/) · [Windows 运行包和样片](https://github.com/kasaikairos/dsh-code-film/releases/tag/v2083.10)

## 可以做什么

- 规划镜头和分镜，用代码搭建 3D 场景并安排物体运动。
- 编排镜头位置、轨迹、构图和光影，预览关键镜头。
- 规划分段配乐，检查渲染与导出质量，在 Windows 上本机导出最高 4K 的视频。

## 成品演示

**《FIRST LIGHT》**是目前唯一一段角色扮演成品视频，时长 1 分 46 秒。

[![《FIRST LIGHT》片中截图](examples/first-light.jpg)](https://github.com/kasaikairos/dsh-code-film/releases/download/v2083.10/FIRST_LIGHT-1080p.mp4)

[1080p 预览版](https://github.com/kasaikairos/dsh-code-film/releases/download/v2083.10/FIRST_LIGHT-1080p.mp4) · [发行页全部下载](https://github.com/kasaikairos/dsh-code-film/releases/tag/v2083.10)

## Windows 安装

1. 安装 [Blender](https://www.blender.org/download/)。先启动一次，确认可正常打开。Blender 用于 3D 建模与渲染，安装脚本需另外检查运行包所用的系统组件。
2. 下载 [Windows x64 运行包](https://github.com/kasaikairos/dsh-code-film/releases/download/v2083.10/DSH-CodeFilm-Runtime-2083.10-Windows-x64.zip)，完整解压。保留解压后的目录结构。
3. 运行解压目录里的 `START-HERE.cmd`。它会检查 Python 3.12 x64、Node.js（至少 22.12）、Chrome、FFmpeg 和本地运行环境，并列出可以选择安装的缺项。Blender 需要按第 1 步安装。
4. 在 DSH（DeepSeek Harness）中加载解压后的 `code-film-render` 文件夹。Skill 入口是 `SKILL.md`，命令行入口是 `film.cmd`。

其他支持 [Agent Skills](https://agentskills.io/specification) 格式的 AI 工具，也可按各自的导入方式加载同一个文件夹。要在工具内执行本机渲染，宿主还需能访问项目文件并运行 Windows 命令。

## 动手示例 · 生成带门洞的墙体

在 GitHub 给出的 [源码目录](https://github.com/kasaikairos/dsh-code-film)里打开 PowerShell。下面的示例只需要 Python，用 [`examples/panel.json`](examples/panel.json) 定义墙体的尺寸、厚度和门洞。

```powershell
python skills/code-film-render/tools/construct.py examples/panel.json --out panel.objects.json
```

生成的 `panel.objects.json` 包含 `objects` 数组。把它加入 [空间镜头配置](skills/code-film-render/topics/space.md)的 `objects`，就可以为墙体安排机位和灯光。更多几何示例见 [构造工具说明](skills/code-film-render/topics/construct.md)。

### 安装排查

- 找不到 `START-HERE.cmd` 或 `engine.zip` 时，确认已下载发行页的 **Windows x64 运行包**并完整解压。发行页同时提供 GitHub 自动生成的源码快照。
- 能加载 Skill 但无法渲染时，先运行 `START-HERE.cmd` 查看缺项，并确认 Blender 可以单独启动。

## 仓库内容

- [`skills/code-film-render/`](skills/code-film-render/) 包含 Skill 入口、专题文档、工具源码和 Windows 启动脚本。
- `engine/` 保存渲染引擎源码和随附素材。安装和渲染请从 Releases 下载带 `engine.zip` 与 `wheels/` 的完整运行包。

## 许可

本项目自有的 Skill 源码和文档采用 [0BSD](LICENSE)。引擎保留 [MIT 许可](engine/LICENSE)，第三方组件和素材适用其随附许可。

## English

DSH Code Film is a Skill for code-driven 3D animation workflows with DeepSeek.

[Skill source](skills/code-film-render/) · [Engine source](engine/) · [Windows runtime and sample video](https://github.com/kasaikairos/dsh-code-film/releases/tag/v2083.10)

### What it does

- Plan shots and storyboards, build 3D scenes in code, and choreograph object motion.
- Set up camera paths, composition, and lighting, then preview key shots.
- Plan music by section, review render and export quality, and export video at up to 4K locally on Windows.

### Finished video

**FIRST LIGHT** is the only finished roleplay sample currently available. It runs for 1 minute and 46 seconds.

[1080p preview](https://github.com/kasaikairos/dsh-code-film/releases/download/v2083.10/FIRST_LIGHT-1080p.mp4) · [All release downloads](https://github.com/kasaikairos/dsh-code-film/releases/tag/v2083.10)

### Setup and usage

1. Install [Blender](https://www.blender.org/download/) for 3D modeling and rendering, then launch it once to verify that it opens.
2. Download the [Windows x64 runtime](https://github.com/kasaikairos/dsh-code-film/releases/download/v2083.10/DSH-CodeFilm-Runtime-2083.10-Windows-x64.zip) and extract the entire archive.
3. Run `START-HERE.cmd` from the extracted folder. It checks for Python 3.12 x64, Node.js 22.12 or later, Chrome, FFmpeg, and the local runtime. Install Blender separately in step 1.
4. Load the extracted `code-film-render` folder as a Skill in DSH (DeepSeek Harness). The Skill entry point is `SKILL.md`, and the command-line entry point is `film.cmd`.

Other AI tools that support the [Agent Skills](https://agentskills.io/specification) format can load the same folder using their own import workflow. For local rendering from within the tool, the host also needs access to the project files and the ability to run Windows commands.

### Worked example · Build a wall with a doorway

Open PowerShell in a checkout of this repository. This example requires only Python. The [input JSON](examples/panel.json) defines the wall dimensions, thickness, and doorway.

```powershell
python skills/code-film-render/tools/construct.py examples/panel.json --out panel.objects.json
```

The output contains an `objects` array. Add those objects to a [3D shot configuration](skills/code-film-render/topics/space.md) to set up a camera and lighting. See the [geometry guide](skills/code-film-render/topics/construct.md) for additional shapes.

#### Troubleshooting

- If `START-HERE.cmd` or `engine.zip` is missing, download and fully extract the **Windows x64 runtime**. GitHub also shows automatically generated source snapshots on the release page.
- If the Skill loads but rendering fails, run `START-HERE.cmd` to check the remaining dependencies and confirm Blender opens on its own.

### Repository layout

- [`skills/code-film-render/`](skills/code-film-render/) contains the Skill entry point, workflow guides, tools, and Windows launch scripts.
- [`engine/`](engine/) contains the rendering engine source and bundled assets.
- [`examples/`](examples/) contains the sample video thumbnail and the geometry example. Download the runtime and videos from [Releases](https://github.com/kasaikairos/dsh-code-film/releases).

### License

The original Skill files and documentation use [0BSD](LICENSE). The engine retains its [MIT license](engine/LICENSE). Third-party components and assets retain their accompanying licenses.

