film.cmd cut --background --plan plan.json --out film.mp4 --preset uhd --fps 24 提交一次。film.cmd cut --wait --out film.mp4 在本地等待并返回摘要；日志在磁盘。返回的 quality 给出画面与配乐检查摘要。完成后核对声画与请求；质量检查详情见输出同名的 .log.txt，后台失败时查看 .cut.log 和 .worker.log 的尾段。也可将计划拖到 render-4k.cmd。需要 Chrome、ffmpeg、ffprobe。

