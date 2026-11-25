在包根目录执行命令。首次安装 Python 依赖 python -m pip install -r requirements.txt 和 npm ci。需要 ffmpeg、ffprobe、Chrome，可用 PUPPETEER_EXECUTABLE_PATH 指定浏览器。

**先判断本次改动的范围。** 已有片只换音乐时，沿用已锁定的 MP4。读取片长、必要的事件时间和音乐要求；写好一份全长音轨后运行 python scripts/revision.py audio --picture 原片.mp4 --track 音乐.wav --out 换乐.mp4。视频与已有字幕流直接复制。只验证某个镜头的运动时，用 python scripts/revision.py shot --plan plan.json --shot 2 --start 1 --seconds 2 --out 检查.mp4（镜内秒数，默认 UHD/24）。局部预览是无声的；正式交付仍检查完整声画。按段创作长片时，项目计划保存跨段的故事、光向和音乐动机；工作会话只读当前段和相邻切点。整片审片集中在成片阶段。

相邻镜头或音乐转折拿不准时，先用一句话预测：此刻观众已知道什么，下一拍最值得发现什么，声音提前或延后会怎样改变理解。让候选方案给出不同的预测，按题意选择；确需验证时只试听或预览发生分歧的一小段。选择写回当前镜头，避免重开整片讨论。

复用同一场景的物体与光源。关键镜头只在 visible 里写一句反事实：什么造成这个可见结果，移走它时哪一处应随之改变。用同一份几何或事件驱动这些变化；镜头里看不出差别的细节无需展开推演。

**新作立项。** 已有 plan 的续作、修改或重渲沿用既定方向。全新项目若用户已指定故事和素材，按其要求执行；其余开放的创作决定，先运行 python -X utf8 scripts/pitch.py 获取本次探索问题。在动笔写场景前，提出两条一句话方案：两条必须在叙述视角、核心证据、揭示顺序中至少两项实质不同。分别说清第一镜看到什么、最后观众发现什么。选择最贴题且能拍清的一条，把选择与理由记入 plan.creative_direction；两个提案无需渲染。根据选中的故事决定使用哪些物件和场所，再选绘图工具。事实主张要有依据，伪纪录片中的虚构材料保持虚构身份。若用户提供旧版，在核心证据与转折处逐项避开其叙事重复。

**写一份计划，按镜取用信息。** plan.json 保存 title、brief 原话及 shots；每镜含 source、seconds、based_on（引用原文）和 visible（观众看见的变化）。连续镜头共享空间关系、光向或声音。大文件先用 python scripts/source_view.py 路径 查符号或 JSON 键，再用 --find 名称 或 --line 行号 定位；每次最多回传 2200 字符。当前镜头只读所需参数或函数签名，已完成的决定与文件路径留在 plan；过程图、生成数据、运行库与长日志保留在磁盘。按题制作额外交付物。换会话接续已有工程时先运行 python scripts/handoff.py --plan 项目/plan.json --out 项目/film.mp4，只带回镜头索引和任务摘要；source 表示源文件存在，审片状态以实际记录为准。

**选择制作入口。** 普通空间镜头写 JSON（template=space，字段见 references/space.md）；图文用 poster 或项目自写 Canvas，风景可用 space 或项目自写着色器。需要原创几何、程序纹理或叠字时，每镜只写一个 JS 模块，导出 spec；可再导出 setup({THREE,scene,root,camera,overlay}) 添加物件，返回接收绝对秒数的更新函数。运行 python scripts/stage.py --module shots/s01.mjs --out shots/s01.html，plan 引用生成的 HTML。工具提供相机、光影、后期、原生尺寸与 DOM 层；需要纸纹、雕刻或浮雕时，可从 ./.codefilm-engine/surfaces.mjs 导入 paintedSurface({width,height,paint,relief,bumpScale,roughness})，两个绘制回调接收 (ctx,w,h)，仅在构建材质时执行。作者只写题材特有部分。现有自定义 HTML 也可直接使用。共用模块只维护一份。

**预览与质量。** python scripts/review_plan.py --plan 项目/plan.json --out 项目/review.jpg。先在联络图检查视线和构图；有疑问时按原帧率核验相关动作，在 UHD 关键帧查纹理、薄边和对焦。只改对应镜头。可加 --shots 2 7 只检查指定镜头，无须反复输出全片草稿。

**正式导出。** Windows 可将定稿 plan.json 拖到包根目录 render-4k.cmd，由本机独立导出到计划同目录；这一阶段可以关闭模型会话。命令行方式： python scripts/cut.py --background --plan 项目/plan.json --out 项目/film.mp4 --preset uhd --fps 24。此命令启动一次持久任务；调用返回后机器继续渲染。看进度用 python scripts/cut.py --status --out 项目/film.mp4，只读取一行。用 --wait --out 项目/film.mp4 可以在本地等待，仅返回最终摘要。等待命令到时退出后，用 --status 查同一任务，状态无变化时无需向模型回传。完成后正常速度看片与试听。失败时看 .worker.log、.cut.log 尾段。中断后同命令恢复已完成镜头。

plan.music 设置全片编曲，单镜 music.sfx 使用局部时间，纯现场可用 style=none。已有定稿混音时 plan.soundtrack 填相对音频路径，复用现成声轨。画面锁定后换声可直接用 make_video.py --picture。合成、缓存及精细度检查均在本地执行。

原创短句可选 plan.music 的 style=ensemble、arrangement=phrases、bpm。镜头 JSON 的 music.cues 中写 {"kind":"phrase","at":"事件名","offset_beats":-1,"voice":"reed","notes":[[62,1],[null,0.5],[65,1]]}。notes 是 MIDI 音高与拍长，null 为休止；可叠加或延迟应答。at 读取本镜 events，缺失时该句留白。直接写 time 则使用秒。
