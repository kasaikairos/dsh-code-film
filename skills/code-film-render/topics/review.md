film.cmd review_plan --plan plan.json --out review.jpg --budget 3 按各镜 review_risks 标签覆盖疑点。局部动作复核用 film.cmd revision shot --plan plan.json --shot 2 --start 1 --seconds 2 --preset draft --out check.mp4。


浏览器长镜头优先用一次轻量检查。film.cmd review_packet 工程/index.html --times 2,14,33,57 --preset uhd --out 工程/review.jpg。一次抓最多四个原尺寸 PNG，再合成一张 JPEG；只向模型打开这一张。需要看细节可加 --roi x y w h，从同一组原帧裁出主体，不再开一次浏览器。通用时间点可取开端、变化开始、变化结果、结尾；用户明确重点时直接取相关点。

首看同时判断构图、动作前后关系、曝光和细节，只记录会影响成片的问题。把相关修改合并；下一次只查改过的时刻或疑点附近的实际帧率短段。审片已经通过时直接提交整片，边际微调留给用户要求。真实动作与时序仍用短片确认。若整片性能未知，挑最重段做一次成本抽查；probe 成本报告与画面包择需使用。必要时用 find 查命中处，完整源码、图片序列和长日志留在项目目录。

用同一套图一次评完整性、材质和动作证据。首轮按最有影响的问题集中修，局部回测一次；再发现关键错误便单独验证对应秒数。对其余边际差异停止重复开同构静帧，不把整段代码或逐帧图带回主会话。最难动作优先用 2–5 秒固定机位片段看速度和遮挡；用一张评审图承接静态细节检查。

多镜同批评审时用 film.cmd review_packet --manifest 工程/samples.json --preset uhd --out 工程/review.jpg。清单是最多四个 {"source":"shot.html","time":1.5} 对象组成的数组，时间按各镜头自己的局部秒数，路径相对清单。输出为一张图，格子与清单顺序一致。同一入口的样本合并到一次浏览器启动。有疑问的动作另取一个实际帧率短段。

要减少审片试错，先固定机位、时间、主体与交付分辨率。选一个最大疑点，写画面应该满足的可验证差异。让项目提供 window.setReviewVariant(id)，只改变该差异对应的参数或机制。film.cmd review_packet 工程/index.html --times 2.5 --variants base shape light --preset uhd --out 对照.jpg。程序只开一个浏览器，回传一张并排图。可加 --roi x y w h、--min-spread 和 --max-clipped，让程序标记暗部、细节区间或曝光明显失败的候选。阈值按本镜意图定义。先选能解释画面变化的版本，再扩到其他镜头；全部候选失败时回到造型、受光或运动机制修改。用原速短段检查切点，最后导向正式出画。
