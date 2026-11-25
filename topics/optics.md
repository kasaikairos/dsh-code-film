# 用着色器构造画面并验证关键帧

先写出题目里主导观感的可见作用，例如光经过介质、表面转动导致反射移动、不同距离导致细节消失。选两到四个最容易露馅的时刻，记录每一帧要看到的变化。保留影响结果的形体与光路，标注有意使用的近似。场景无需套用题材预设。

写原创 GLSL ES 3 片元函数 vec3 shade(vec2 pixel)，pixel 为以左下角为原点的成品像素坐标。可用 resolution、time（秒）。返回 0–1 的线性颜色，封装层转换到 sRGB。filmCoverage(field) 根据屏幕导数平滑正值为内部的边线；filmTransmit(surface,mediumLight,extinction,distance) 用指数透射混合表面和介质光；filmFresnel(F0,cosTheta) 给出掠射反射。也可完全自定义；要保留 HDR 高光时，在 shade 中自行做色调映射。三个辅助函数不替代光照或几何设计。

运行 python tools/shader.py shot.glsl --seconds 6 --out shot.html，也可用 film.cmd shader。输出 HTML 无资源依赖；浏览器加 ?preview=1 播放。宿主有 Python 时可直接生成页面；最终渲染交给已有的 WebGL2 浏览器和编码环境。

film.cmd timeline shot.html --preset uhd --stills 0.5,2,4 --out review/shot 输出原尺寸 PNG 和编号对应时间的简报，不执行视频编码。用与最终输出一致的尺寸检查细线和材质。只在最费解的过渡点出短片；确认后通过 timeline 或 cut 导出。画面锁定后，后台渲染与纯器乐合成可并行安排，合成声音后可用视频流复制封装。加时间轴截图耗时作为项目记录，缩略图按需返回给模型。

filmWavePacket(x,time,at,origin,speed,width,frequency) 可给风带、波纹或扰动一个局部行进范围。宽度须大于零。返回位移和沿 x 的变化率；让同一状态同时驱动形体、反射或光影。其用途是为画面提供可读的运动事件，具体速度、尺度、反应延迟由场景决定。

写实镜头先核对形体证据：近景的厚度、接缝、倒角、接触阴影和运动中变化的反射。每个重要表面选一个可从动作或光线看懂的材质特征。结构与遮挡用几何；稳定表面可烘焙，光照与视角相关的响应保留逐帧计算。规律细纹用 filmResolvedSine(phase) 将低于像素可分辨尺度的零均值起伏平滑收敛，降低摩尔纹和闪烁。高反差线条在交付尺寸看短片确认；平面写意和剪影按用户风格验收。

若天空用射线，水或建筑用网格，film.cmd optical_camera 工程/optical-camera.mjs 提供共享光学相机。opticalCamera(eye,yaw,pitch,verticalFov,aspect) 返回射线基和列主序 view。角度是弧度，前方为 +Z，projectDirection/projectPoint 返回 NDC。两种绘制路径共用这套相机。auditProjection(camera,actualViewProjection,points,width,height) 量化实际网格矩阵与解析射线的最坏像素差。至少用带偏航、俯仰的镜头测试，正对镜头可能掩盖转置错误。

用 flatWaterGlint(eye,direction,waterLevel) 求平水镜面落点以核对反射；有浪时高光随法线分散。比例由视角和镜头统一决定。angularDiameterPixels 给中央附近的投影直径，可计算选题要求的像素大小；需要更大的太阳时优先调整镜头。片元波纹用 filmWaveBand(axis,wavelength,dFdx(worldXZ),dFdy(worldXZ)) 按实际像素足迹限制近远细纹，未分辨掉的斜率可累加到材质粗糙度。最后区分故意加的成像颗粒与表面采样闪烁。
