/* A moving packet in object coordinates. Speed and width use the same units as x.
   Returns height and its spatial derivative for coherent normals/reflection. */
vec2 filmWavePacket(float x, float time, float at, float origin,
                    float speed, float width, float frequency) {
    if (time <= at) return vec2(0.0);
    float t = time-at;
    float d = x-origin-speed*t;
    float q = d/width;
    float envelope = (1.0-exp(-8.0*t))*exp(-q*q);
    float phase = frequency*d;
    return envelope * vec2(sin(phase),frequency*cos(phase)-2.0*q/width*sin(phase));
}
