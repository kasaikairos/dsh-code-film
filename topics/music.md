# 按画面段落写配乐

先确定每段画面和情绪在哪里变化，再写对应乐句。可以用同一动机让不同乐器接棒，也可以变节奏、和声、织体或用一段留白。音乐边界按叙事安排，段内允许比切镜晚进、早收。逐段做一处可听见的变化，先清楚交代主旋律和应答。

`film.cmd score_plan music.json --out score.json` 编译乐谱，`film.cmd score_wav score.json score.wav` 合成。示例为一个带前景与留白的时序。

```json
{
  "seconds": 6,
  "sections": [
    {
      "id": "arrival", "start": 0, "end": 3, "bpm": 84,
      "phrases": [{"time": 0.15, "role": "lead", "voice": "flute",
                   "notes": [[69,0.75],[72,0.75],[74,1.5]]}]
    },
    {"id": "listening", "start": 3, "end": 6, "silence": true}
  ]
}
```

sections 覆盖全片，首段从 0 开始，相邻段共用边界。各段独立设置 bpm、phrases、harmony 和 quiet，段内 time 与 quiet 均为相对段首秒数。没有配乐的段填 silence=true。原样回归可填 reprise=true。编译结果的 sections 给出绝对秒数、速度和实际使用的乐器。和分镜共用时间时，改用 `score_plan music.json --board board.json --out score.json`，各段以 `"shots":["选中的镜头ID"]` 替代 start/end。一个音乐段可覆盖相邻多个镜头。需要跨过切点延续乐句时，把这些镜头放在同一段里面。

单簧管 clarinet、中提琴 viola、大提琴 cello、长笛 flute、小提琴 violin、巴松 bassoon 和柔奏立式钢琴 piano 都有随包录音。根据镜头选主奏，给乐器留出合适音区。长笛适合轻而连贯的线条，巴松可做有形状的低声部，钢琴适合稀疏落音。采样来源和 CC0 许可随引擎保存。

从 0–2 秒、段落边界和结尾各试听一小段。画面锁定后执行 `film.cmd revision audio --picture 原片.mp4 --track score.wav --out 成片.mp4`。用 cut 时也可将编译后的 score.json 对象放入 plan.music，或使用定稿 WAV 作为 plan.soundtrack。

单段可继续使用原有的 seconds、bpm、phrases、harmony、quiet 格式。每句含 time、role（lead、response、bed 或 harmony）、voice、notes（[MIDI 音高, 拍长] 数组，null 音高为休止）及可选 level。镜头内原有 music.cues 的 time 是镜内秒数，也可用 at 指向事件。全片显式 cues 优先。纯现场声可选 style=none。


希望避免逐音敲击时，可选 arrangement=legato。用 phrase 写整句，音高过渡共用振荡相位和呼吸包络；null 形成真正休止。voice=bow 为持续弓弦，其余可用 reed。按段写旋律与对位，试听前不选旧声轨作默认。

需要检查主题是否展开时，给 score_plan 加 --developed。它按音程序列找开头动机、对比句及回归，允许回归时移调。主句和应答依次占前景。quiet 指明需要完全静音的区间，留给环境声或画面停顿。

原创旋律可用 harmony 自动配和声。每个窗口写 time（秒）、beats、chord（MIDI 音级 0–11，从根音开始）、voice（cello、viola、bassoon 或 piano）和可选 level。工具在可演奏音区里选离主句足够远且相邻跳进较小的声部。同一乐器已有旋律或应答的窗口交给另一件乐器。

画面定稿后的现场声可调用 film.cmd sound_design 声音设计.json --music 乐句.wav --out 混音.wav。声音设计含 seconds、events（直接复用项目事件时间）和 sounds。每条含 id、at（事件名或秒数）、kind（contact、friction、air、water），持续声再填 until；可用 material（contact: wood/metal/stone/soft；friction: fabric/paper/wood/gravel）、level、pan（-1 至 1，或 [起,止]）、distance（相对距离）和 duck（0 至 .4）。用户想留白时省略对应声部。只为帮助听出材质、方向或后果的事件加声；把环境、近景动作和器乐各自试听一处，再合音。混音可在画面出片时后台完成，合成用 revision audio 复用视频流。
