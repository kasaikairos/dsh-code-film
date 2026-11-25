film.cmd stage 会把两个模块部署到镜头目录的 .codefilm-engine。使用 stage 时可从镜头目录的 .codefilm-engine/brush.mjs 导入。

3D 近景先建对轮廓、厚度和接缝，再考虑材料。调用 surfaces.mjs 的 materialField({width,height,color,sample,bumpScale})；sample(u,v) 返回 {height,roughness,metalness}，三值均为 0..1。用一个物理原因驱动相关通道，例如手指常碰的区域会磨平，在侧光下高光变窄。bumpScale 用场景单位，轮廓破损仍需几何。金属需有可反射环境，可使用 space 的 environment。材质构建一次，同材质的物件复用实例。

2D 先用代码画出原创的大明暗、遮挡和轮廓，将不透明底稿 Canvas 交给 brush.mjs 的 brushLayer(canvas,{seed,sizes,direction})。sizes 是由粗至细的像素半径，可省略；direction(x,y,r) 返回局部笔向（弧度），省略时沿亮度等值线。返回可复用的 Canvas。不同动势各做一层，在物体局部坐标生成，运动时变换整层，遮罩放在笔触之后。这个工具只处理笔法，姿态、透视和结构由底稿承担。
