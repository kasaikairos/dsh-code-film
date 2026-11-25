---
name: code-film-render
description: 从文案原创设计和导出有声代码视频，支持原生 UHD、定制绘图、分镜复用及长片后台导出。
metadata:
  version: "2081.3"
---

先从题意和你已有的领域知识构造场景。为每镜写出观众应能辨认的变化，决定哪些物体、笔触、声音或动作共用同一个原因。在脑中改变这个原因，预测画面哪处会随之改变。把选定的解释落实到场景代码，题材、造型、配色与镜头由你决定。

plan.json 保存 title、brief、shots；每镜写 source、seconds、based_on、visible。需要诊断时，用 review_risks 字符串数组标记该镜可能失败的具体原因，共因共用标签。预算允许检查 K 镜时运行 python scripts/review_plan.py --plan plan.json --out review.jpg --budget K。它选能覆盖更多不同疑点的镜头。联络图用于看构图；动作、声音和细节疑点分别用局部原帧率片段、试听、UHD 原帧核实。将结果记回磁盘，下一镜只读取必要决定。

正式导出在本机运行 python scripts/cut.py --background --plan plan.json --out film.mp4 --preset uhd --fps 24。可用 --wait --out film.mp4 等待摘要。首次安装、创作入口、局部审片及音轨修改，按需查 references/workflow.md 对应段落。
原创写实表面或绘画镜头先查 references/art.md，按题目选择材质场或方向笔触。
