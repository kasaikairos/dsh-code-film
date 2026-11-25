# DSH Code Film

面向 DeepSeek 的代码驱动 3D 动画制作 Skill，包含场景构建、分镜、镜头与运动编排，以及 Windows 本机渲染与导出流程。

## Windows 安装

1. 安装 [Blender](https://www.blender.org/download/)。先启动一次，确认可正常打开。Blender 用于 3D 建模与渲染，安装脚本需另外检查运行包所用的系统组件。
2. 从 [Releases](https://github.com/kasaikairos/dsh-code-film/releases) 下载 Windows x64 运行包，完整解压。保留解压后的目录结构。
3. 运行解压目录里的 `START-HERE.cmd`。它会检查 Python 3.12 x64、Node.js（至少 22.12）、Chrome、FFmpeg 和本地运行环境，并列出可以选择安装的缺项。Blender 需要按第 1 步安装。
4. 在支持 Skill 的 DeepSeek 工作环境中导入解压后的 `code-film-render` 目录。Skill 入口是 `SKILL.md`，命令行入口是 `film.cmd`。

## 仓库内容

- `SKILL.md` 与 `topics/` 提供 Skill 入口与工序说明。
- `tools/` 提供分镜、场景、运动、镜头和渲染检查工具。
- `START-HERE.cmd`、`setup.ps1` 与 `film.cmd` 提供 Windows 命令入口。
- `engine/` 保存渲染引擎源码和随附素材。安装和渲染请从 Releases 下载带 `engine.zip` 与 `wheels/` 的完整运行包。

## 许可

本项目自有的 Skill 源码和文档采用 [0BSD](LICENSE)。引擎保留 [MIT 许可](engine/LICENSE)，第三方组件和素材适用其随附许可。
