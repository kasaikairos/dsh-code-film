# 正式导出前的质量检查

用 film.cmd preflight index.html --profile gate.json 单独检查，或在已有 timeline 导出命令末尾加 --gate gate.json。前置检查成功才启动全片编码。先查史实记录、看片结论和实际纯音乐音轨，再开浏览器取样。正式混音沿用通过检查的音乐文件。每轮只修返回的问题，用同一条件复测。资料和整段日志留在项目目录。

gate.json 示例（所列阈值只展示格式）：

```json
{
  "samples": [{"time": 2.5, "roi": [0.2, 0.2, 0.5, 0.5], "minDetailCoverage": 0.2}],
  "facts": [{"id": "costume", "claim": "这个人物使用该式服饰", "source": "https://example.org/catalog/item", "evidence": "馆藏条目支持的具体年代、地点和用途", "sceneYears": [-1320, -1300], "supportedYears": [-1350, -1280], "verdict": "supported"}],
  "reviews": [{"id":"hero", "evidence":"工程内关键帧文件或时间", "observation":"观察到的造型、笔法和可读性", "verdict":"pass"}],
  "music": {"file": "score.wav"}
}
```

按任务添加适用项。samples 必须覆盖主要画风或材质的关键镜头；roi 是归一化的左上角、宽、高。细节覆盖率统计在两个尺度都有足够变化的小块比例，适用于明确要求纹理或结构的主体局部。对刻意留白、剪影、极简设计保留其风格。粒子、噪点和交叉线也可能得高分；在 reviews 看真实关键帧，判断形体、层次、光影和材质是否符合题意。需要确认动作就调用 motion_audit 或看实际帧率的局部样片。旧版 minSpread、maxClipped 仍可用。

排查颗粒用同机位平坦暗面、天空或无纹理背景。例 `{"viewport":[3840,2160],"samples":[{"time":2,"compareTime":2.041666667,"roi":[0.12,0.16,0.15,0.1],"maxGrain":0.003,"maxFlicker":0.003}]}`。maxGrain 为原像素 RGB 高频残差，maxFlicker 为两时刻同一位置的 RGB 差，均为归一化 RMS。门槛可按素材和参考实测调整。预设 viewport 为 1920×1080，查原生 4K 时选择 3840×2160。闪烁检测只用于画面应稳定的区域和时段，镜头运动时先锁机位取对照。避免在水面、衣纹或预期运动的细节上套静态门槛。

space、内置 3D 场景与 Blender 后期的 post.grain 默认是 0，风格确实需要颗粒时可显式设置。自定义 Canvas/WebGL 检查项目自己的 grain、noise、dither 图层。阴影、反射或体积介质出现闪烁时，先检查该通道的采样、抖动或几何遮挡，再同条件预览。保留材质纹理和清楚的边缘。

可辨识的史实拆成具体主张，先核对原始资料再填 verdict；年代取证据支持的范围。疑点用 unresolved，明确的虚构用 fiction 并填写画面中使用的 label。脚本检查记录是否齐备及年代是否重叠。地区、身份、史料可信度和细节实际是否画出来，都由看片与读来源确认。发布规格要求的审美结论用 reviews 记录；疑点仍未解决时留 fail。

music.file 相对 gate.json。默认检查高频能量和最密集两秒的亮起音。超过门槛时，先试听报告位置，延长起音、减少重复敲击或重写乐句。maxBrightAttacksPerSec 与 maxBrightEnergyShare 可按经过试听的候选校准，默认 2.5 与 0.45 是初始筛查值。安静或高频单薄也可能通过，所以还要听旋律、配器和段落发展。用户指定纯音乐时结合配器与试听确认无人声。音轨听感疑点也可写入 reviews。
