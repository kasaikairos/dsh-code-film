import json
import secrets

# Questions direct exploration; the model supplies all subject matter.
axes = [
    ["观众跟随谁查证", "观众能接触哪类证据", "哪个地点能限制观众的视野"],
    ["从后果追溯原因", "跟随一次完整调查", "让两种解释逐步相遇", "围绕一次当场验证展开"],
    ["哪一件事会推翻开场判断", "什么信息应留到最后揭晓", "谁对同一件事有另一种解释"],
]
rng = secrets.SystemRandom()
print(json.dumps([rng.choice(axis) for axis in axes], ensure_ascii=False))
