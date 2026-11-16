// 노트 색을 OKLab 공간에서 섞는다. RGB 평균보다 탁해지지 않고 눈으로 본 중간색에 가깝다.

const toLinear = c => (c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
const toGamma = c => (c <= .0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - .055);

function hexToOklab(hex) {
  const [r, g, b] = [1, 3, 5].map(i => toLinear(Number.parseInt(hex.slice(i, i + 2), 16) / 255));
  const l = Math.cbrt(.4122214708 * r + .5363325363 * g + .0514459929 * b);
  const m = Math.cbrt(.2119034982 * r + .6806995451 * g + .1073969566 * b);
  const s = Math.cbrt(.0883024619 * r + .2817188376 * g + .6299787005 * b);
  return [
    .2104542553 * l + .793617785 * m - .0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + .4505937099 * s,
    .0259040371 * l + .7827717662 * m - .808675766 * s,
  ];
}

function oklabToHex([L, a, b]) {
  const l = (L + .3963377774 * a + .2158037573 * b) ** 3;
  const m = (L - .1055613458 * a - .0638541728 * b) ** 3;
  const s = (L - .0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + .2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s,
    -.0041960863 * l - .7034186147 * m + 1.707614701 * s,
  ];
  return '#' + rgb.map(c => Math.round(Math.min(1, Math.max(0, toGamma(c))) * 255).toString(16).padStart(2, '0')).join('');
}

/** 여러 색의 평균. 섞일수록 채도가 빠지는 것을 막기 위해 채도를 원래 평균만큼 되돌린다. */
export function blendColors(hexes) {
  if (!hexes.length) return null;
  if (hexes.length === 1) return hexes[0];
  const labs = hexes.map(hexToOklab);
  const avg = labs.reduce((sum, lab) => sum.map((v, i) => v + lab[i] / labs.length), [0, 0, 0]);
  const chroma = Math.hypot(avg[1], avg[2]);
  const wanted = labs.reduce((sum, lab) => sum + Math.hypot(lab[1], lab[2]), 0) / labs.length;
  const boost = chroma > 1e-4 ? Math.min(1.6, (chroma + (wanted - chroma) * .6) / chroma) : 1;
  return oklabToHex([avg[0] + .015, avg[1] * boost, avg[2] * boost]);
}

/** 두 색 사이를 t만큼 섞는다. */
export function mixColors(a, b, t) {
  const A = hexToOklab(a), B = hexToOklab(b);
  return oklabToHex(A.map((v, i) => v + (B[i] - v) * t));
}
