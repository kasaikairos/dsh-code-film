# 由叙事事件求机位

先写镜头要交代的空间关系，再决定保持、推进、后拉、环绕或跟随。开场可用前景和主体的视差建立空间。接触时可停住镜头给动作留时间。只有换视角才能读到的细节可另立拍摄机位。aspect 使用交付画幅。

`film.cmd director camera-input.json --board board.json --out camera-keys.json` 读取 storyboard 已选的镜头。每条 beats 填对应的 shot（取 shots[].id），工具从分镜取出起止时间。也可省略 --board，直接为每条 beats 填 t（切入的绝对秒数）。相机参数和场景事件应使用同一时间轴。

输入包含 candidates（每项 az、el 为度，dist 为场景单位，fov 为垂直视角度数）和 beats（每项 t 为切入秒数，target 为构图中心 xyz，samples 是本拍中不同动作时刻的坐标快照）。每个 samples 条目填 points（至少两个必须同时看清的世界坐标）与可选 boxes（当时的世界坐标遮挡盒，每个为 [minXYZ,maxXYZ]）。遮挡盒只放独立的不透明遮挡物；重要点放在真实可见表面。数据应从实际场景尺寸和运动求出。margin 是画面边缘留量，span 是主体最长投影轴占画面比例，两项可按叙事决定；continuity 控制跨拍视角变化的成本。

在镜头中推进可加 `"move":{"start":1,"end":3,"distScale":0.8}`。start/end 是全片秒数，start 默认从本镜起点开始，接入 --board 时 end 默认停在本镜末帧。distScale 小于 1 推进，大于 1 后拉。用角度增量 azDelta 或 elDelta 环绕，用 move.target 给出跟随终点。可以组合这些变化。每次移动按实际构图填写开始、中间和结束的 samples[].t，采样点用当时的场景坐标，接触或快速遮挡处多加一个。输出是平滑进停的关键帧。cut 标记切入，镜内移动和停留使用 cut=false。固定镜头可省略 move。

把结果 keys 放进 space JSON 的 camera.keys，设置 handheld=0。自定义 3D 时间轴可执行 `film.cmd camera_track 工程/camera-track.mjs` 导出模块。把关键帧写进项目代码或读入 JSON，调用 `const at = cameraTrack(keys)`，每帧用 `at(t)` 给出 position、target、fov 和 focus，再更新项目相机。2D 镜头可用同样的构图目标定义中心、画面尺度和停留，再给画布分层做平移和视差。

遮挡或出框会淘汰候选。无解时调整机位、目标或移动幅度，用同一组事件重试。粗盒和离散采样只检查提供的点和时刻。导出前静音看一次移动和切点，核对走向、视线、接触和停留。
