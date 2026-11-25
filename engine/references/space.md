JSON 顶层字段：

| 字段 | 说明 |
|---|---|
| `camera` | `az/el/dist/fov/target/azDrift/distDrift/focus`；`mode: orbit|dolly`；`handheld` 轻微手持 |
| `lights` | `ambient/hemi/dir/point/spot`；`intensity` 是物理量级，室内 5–20、路灯 30–60 |
| `ground` | `tint/rough/reflectivity/puddle/ripple/sheen/tex/y`；湿地 rough 0.2–0.35，抛光石材 0.05–0.15 |
| `objects` | `box/cyl/sphere/plane/torus/lathe/extrude/instanced/group`，带 `mat{albedo,rough,metal,emissive,tex,opacity,texScale}` |
| `atmosphere` | `fog{color,density}`、`rain{count,speed,slant,opacity,area}` |
| `post` | `exposure/bloom/bloomThresh/dof/dofMax/grain/vignette/ca/sat/contrast` |
| `anim` | 灯或物体上：`t0/t1/posFrom/posTo/targetFrom/targetTo/rotFrom/rotTo/ease` |

**三条硬规矩**（都是实测踩出来的）：
1. 落地物的 y 用“高度/2”推，不手填；悬空超过 0.45 m 的物体会丢掉接触阴影。
2. 反光靠“平面反射 + 粗糙度竖向拉伸 + 前景物遮挡”三件事，别用整屏模糊贴图；灯一动，反光要跟着动。
3. 玻璃后面要有东西（货架、灯管、内墙），否则就是一整块发光白板。


运动用 scripts/action.py 的 Scene.path、roll、slide；局部对焦用 camera.keys 的 target_ref={name,local}。开口穿越可用 scripts/opening_check.py 校验。
方向光可设 shadowCenter（三维世界坐标）、shadowSpan（光空间正方形覆盖宽度，世界单位）。覆盖整个动作范围、投影物和承影区并留余量。广域长镜头保持默认 32；近景先试主体包围宽度的两到三倍，核对动作两端及侧光下影子边缘。
近景箱体可选 edgeRadius（世界单位），给制造形成的圆边一条能接住侧光的轮廓。半径至多为最短边的一半。棱角锐利的构件保持原样。
反光金属缺少周围环境时可设 environment，如 {"fill":"#25262b","intensity":0.7,"cards":[{"pos":[-2,2,2],"size":[1,3],"color":"#fff1db","intensity":2}]}。卡片面朝原点，只贡献环境光与材质反射；方位跟随镜头里合理的窗、灯或墙面，避免让不同空间都出现相同高光。


### 共享光影

`ground.physicalLighting=true` 启用 Three 灯光与阴影同源的地面着色。阴影衰减各灯自身的直射分量，环境光与平面反射单独计算。场景中的透明薄片或自发光物仍需要按材质选择投影。方向光用 `dir` 和 `shadowSpan`/`shadowCenter` 定义方向与范围。把同一灯移到另一侧，阴影应移到相反方向。在此模式中，静态接地遮蔽与方向投影分开处理。

`kind=instanced` 可传 `transforms` 替代随机铺放，每项支持 `pos`、`rot`、`scale` 与 `color`。叶片用 `base=leaf`，姿态从叶柄/叶根为原点；可选 `blade=true` 及 `wind.direction`/[世界 X,Z] 与 `wind.strength`。建议从 construct plant 生成。
