const fixed = value => ({ a: 0, k: value });
const easingIn = { x: .25, y: 1 };
const easingOut = { x: .2, y: .1 };
const frames = (...values) => ({
  a: 1,
  k: values.map(([t, ...s], i) => i === values.length - 1 ? { t, s } : { t, s, i: easingIn, o: easingOut }),
});

function shapeLayer(index, name, position, opacity, scale, contents) {
  return {
    ty: 4, ind: index, nm: name, ip: 0, op: 72, st: 0,
    ks: { p: position, a: fixed([0, 0, 0]), r: fixed(0), o: opacity, s: scale },
    shapes: contents,
  };
}

const warmLight = [.99, .89, .62, 1];
const stroke = (width, opacity) => ({ ty: 'st', c: fixed(warmLight), w: fixed(width), o: fixed(opacity), lc: 2, lj: 2 });

export default {
  v: '5.12.0', fr: 60, ip: 0, op: 72, w: 640, h: 640, nm: 'Sillage glass caustic', assets: [],
  layers: [
    shapeLayer(1, 'Prismatic glint', frames([0, 366, 365, 0], [24, 386, 344, 0], [58, 354, 300, 0]),
      frames([0, 0], [9, 0], [19, 100], [38, 35], [60, 0]),
      frames([0, 17, 17, 100], [22, 70, 70, 100], [56, 95, 95, 100]),
      [{ ty: 'sh', ks: fixed({ c: true, v: [[0,-71],[5,-7],[63,0],[5,6],[0,71],[-5,6],[-63,0],[-5,-7]],
        i: Array.from({ length: 8 }, () => [0,0]), o: Array.from({ length: 8 }, () => [0,0]) }) },
      { ty: 'fl', c: fixed([1, .97, .86, 1]), o: fixed(92), r: 1 }]),
    shapeLayer(2, 'Reflected ripple', fixed([365, 345, 0]),
      frames([0, 0], [14, 0], [23, 61], [64, 0]),
      frames([0, 16, 14, 100], [64, 176, 153, 100]),
      [{ ty: 'el', p: fixed([0,0]), s: fixed([247, 143]), d: 1 }, stroke(1.25, 75)]),
    shapeLayer(3, 'Outer caustic', fixed([365, 345, 0]),
      frames([0, 0], [23, 0], [32, 41], [68, 0]),
      frames([0, 12, 10, 100], [68, 213, 180, 100]),
      [{ ty: 'el', p: fixed([0,0]), s: fixed([238, 132]), d: 1 }, stroke(.8, 58)]),
  ],
};
