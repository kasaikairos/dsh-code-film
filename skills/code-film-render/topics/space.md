空间镜头 JSON 使用 template=space，定义 camera、lights、ground、objects。只查需要的字段：film.cmd source_view references/space.md --find camera（替换关键词）。自定义模型可通过 stage 运行；材质或笔触查 art。

写实明暗用 ground.physicalLighting=true。对象和地面使用同一个光源数组与遮挡贴图。dir.dir 是光线的传播方向。用小到能包住主体、地面投影和机位运动范围的 shadowSpan；需要偏移时填 shadowCenter。点光、聚光要投影时设 shadow=true。静态镜头的遮挡贴图只算一次；动件或风动时正常更新。旧场景可沿用原参数。纯天空或自定义着色器需要共用光源参数时读 optics。
