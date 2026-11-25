---
name: code-film-render
description: 原创代码短片、分段配乐、镜头与 Windows x64 本机 4K 导出。
metadata:
  version: "2083.10"
---
按题面锁定画幅、帧率、采样和交付规格。先确定每段必须看清的变化。一个机位能交代过程时可保持或运镜，局部证据读不清时切近景。多段用 storyboard，3D 运镜用 director。配乐用 music 卡的 sections，逐段安排主奏、变奏和留白。默认原创纯器乐，避免连续铃音、亮拨弦和逐动作敲音。

首次本机出片，在技能目录执行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./setup.ps1 -Mode check`。向用户说明缺项的用途、影响和安装来源，经同意后用同一脚本执行 `-Mode apply -Approved "id1,id2"`。命令入口为 `film.cmd`。

先按 topics/ 中当前工序取一张卡。构思用 plan、storyboard，搭景用 space、art、construct，动作和相机用 motion、director，光影用 optics，风水用 environment，专业题材用 design，声音用 music，出片用 timeline 和 export。

长片按 performance 卡执行。先预览最难的镜头和接缝，定稿后后台按原规格出画。已出画从母版审片，改乐复用视频流。只读当前镜头的简报与源码命中段，长日志、源码和原帧留在工程目录。默认关全屏颗粒，纹理、暗部和闪烁按 quality 卡核查。纯代码盲测用 timeline 卡的 `preflight --source-only`。
