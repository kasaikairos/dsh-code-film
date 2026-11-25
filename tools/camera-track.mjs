// Sample the absolute-time camera keys produced by director.
export function cameraTrack(keys) {
  if (!Array.isArray(keys) || !keys.length || keys.some((key, index) =>
    !Number.isFinite(key.t) || (index > 0 && key.t <= keys[index - 1].t))) {
    throw new Error("camera track needs keys in increasing time order");
  }
  return time => {
    let index = 0;
    while (index + 1 < keys.length && time >= keys[index + 1].t) index++;
    const a = keys[index];
    const b = keys[index + 1];
    const fraction = b && !b.cut ? Math.max(0, (time - a.t) / (b.t - a.t)) : 0;
    const eased = fraction * fraction * (3 - 2 * fraction);
    const value = (from, to) => from + (to - from) * eased;
    const next = b && !b.cut ? b : a;
    const az = value(a.az, next.az) * Math.PI / 180;
    const el = value(a.el, next.el) * Math.PI / 180;
    const dist = value(a.dist, next.dist);
    const target = a.target.map((coordinate, axis) => value(coordinate, next.target[axis]));
    const position = [
      target[0] + Math.sin(az) * Math.cos(el) * dist,
      target[1] + Math.sin(el) * dist,
      target[2] + Math.cos(az) * Math.cos(el) * dist,
    ];
    return {position, target, dist, fov: value(a.fov, next.fov), focus: value(a.focus, next.focus)};
  };
}
