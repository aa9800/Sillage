import React, { useEffect, useRef } from 'react';

// 화면 전체에 깔리는 실크 같은 색 흐름. 병 위치(origin)에서 색이 번져 나가고,
// 노트가 바뀌면 물결 링이 한 번 퍼진다. 첫 화면과 상담 화면이 같은 캔버스를 공유한다.

const vertex = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`;

const fragment = `
precision highp float;
uniform vec2 uRes;
uniform float uTime;
uniform vec3 uA, uB, uC;
uniform vec2 uOrigin;
uniform float uDark, uReach, uFlash, uRipple;

vec3 permute(vec3 x){ return mod(((x * 34.) + 1.) * x, 289.); }
float snoise(vec2 v){
  const vec4 C = vec4(.211324865405187, .366025403784439, -.577350269189626, .024390243902439);
  vec2 i = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = x0.x > x0.y ? vec2(1., 0.) : vec2(0., 1.);
  vec4 x12 = x0.xyxy + C.xxzz; x12.xy -= i1;
  i = mod(i, 289.);
  vec3 p = permute(permute(i.y + vec3(0., i1.y, 1.)) + i.x + vec3(0., i1.x, 1.));
  vec3 m = max(.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.);
  m = m * m; m = m * m;
  vec3 x = 2. * fract(p * C.www) - 1.;
  vec3 h = abs(x) - .5;
  vec3 a0 = x - floor(x + .5);
  m *= 1.79284291400159 - .85373472095314 * (a0 * a0 + h * h);
  vec3 g; g.x = a0.x * x0.x + h.x * x0.y; g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130. * dot(m, g);
}
float fbm(vec2 p){ float s = 0., a = .5; for(int i = 0; i < 3; i++){ s += a * snoise(p); p = p * 1.9 + 11.7; a *= .42; } return s; }

void main(){
  vec2 uv = gl_FragCoord.xy / uRes;
  float aspect = uRes.x / uRes.y;
  vec2 p = vec2(uv.x * aspect, uv.y);
  vec2 o = vec2(uOrigin.x * aspect, uOrigin.y);
  float t = uTime * .045;

  // 실크 같은 큰 물결: 낮은 주파수 도메인 워핑
  vec2 q = vec2(fbm(p * .42 + vec2(0., t)), fbm(p * .42 + vec2(5.2, -t * .8)));
  vec2 r = vec2(fbm(p * .55 + 1.7 * q + vec2(1.7, 9.2) + t * .5), fbm(p * .55 + 1.7 * q + vec2(8.3, 2.8) - t * .4));
  float silk = fbm(p * .45 + 1.35 * r);
  float fold = smoothstep(-.6, .7, silk);
  float sheen = pow(1. - abs(snoise(p * .7 + 1.2 * r + t * .3)), 9.) * .38;
  // 병에서 번져 나오는 범위
  float d = distance(p, o);
  float warpD = d + .12 * fbm(p * 1.6 + t * 1.3);
  float reach = smoothstep(uReach + .35, uReach * .15, warpD);

  vec3 paper = mix(vec3(.936, .922, .894), vec3(.062, .062, .058), uDark);
  vec3 tint = mix(uC, uB, fold);
  tint = mix(tint, uA, smoothstep(.55, 1., fold) * .8);
  tint = mix(tint, vec3(1.), sheen * (.35 - uDark * .2));
  float strength = mix(.78, .55, uDark);
  vec3 col = mix(paper, mix(tint, tint * .42, uDark), reach * strength);

  // 병 바로 뒤의 은은한 조명
  float halo = exp(-d * d * 9.);
  col += mix(uA, vec3(1.), .4) * halo * mix(.22, .16, uDark);

  // 노트를 고를 때 퍼지는 물결 링
  if (uRipple > 0. && uRipple < 1.) {
    float ring = uRipple * 2.1;
    float wob = d + .035 * snoise(p * 4. + t * 4.);
    float band = exp(-pow((wob - ring) * 14., 2.)) + .45 * exp(-pow((wob - ring * .82) * 18., 2.));
    col = mix(col, mix(uA, vec3(1.), .55), band * sin(3.14159 * uRipple) * .55);
  }

  // 입장 전환 때 병 모서리에서 번지는 빛
  float flashR = uFlash * 2.4;
  float bloom = smoothstep(flashR, flashR * .2, d) * sin(3.14159 * clamp(uFlash, 0., 1.));
  col = mix(col, mix(uA, vec3(1.), .75), bloom * .85);

  // 가장자리 비네팅
  vec2 vu = uv - .5;
  col *= 1. - dot(vu, vu) * mix(.18, .55, uDark);
  gl_FragColor = vec4(col, 1.);
}`;

const rgb = hex => [1, 3, 5].map(i => Number.parseInt(hex.slice(i, i + 2), 16) / 255);

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
  return shader;
}

// target: { tones:[hex,hex,hex], dark:0..1, reach:0..1.6 }  ripple/flash는 신호 숫자가 바뀔 때 1회 재생
export function Backdrop({ target, ripple, flash, originRef }) {
  const canvasRef = useRef(null);
  const live = useRef({ target, ripple, flash });
  live.current.target = target;
  useEffect(() => { if (ripple) live.current.rippleAt = performance.now(); }, [ripple]);
  useEffect(() => { if (flash) live.current.flashAt = performance.now(); }, [flash]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const gl = canvas.getContext('webgl', { antialias: false, premultipliedAlpha: false, powerPreference: 'high-performance' });
    if (!gl) { canvas.classList.add('no-webgl'); return; }
    let program;
    try {
      program = gl.createProgram();
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vertex));
      gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fragment));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    } catch (error) {
      console.warn('backdrop shader', error);
      canvas.classList.add('no-webgl');
      return;
    }
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, 'p');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = name => gl.getUniformLocation(program, name);
    const U = Object.fromEntries(['uRes', 'uTime', 'uA', 'uB', 'uC', 'uOrigin', 'uDark', 'uReach', 'uFlash', 'uRipple'].map(n => [n, u(n)]));

    const reduce = matchMedia('(prefers-reduced-motion: reduce)');
    const cur = { tones: live.current.target.tones.map(rgb), dark: live.current.target.dark, reach: live.current.target.reach, ox: .62, oy: .5 };
    let frame = 0, last = performance.now(), width = 0, height = 0;
    const scale = .55; // 부드러운 색면이라 낮은 해상도로 그려도 티가 나지 않는다

    function resize() {
      width = canvas.clientWidth; height = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      gl.viewport(0, 0, canvas.width, canvas.height);
    }
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();

    function draw(now) {
      const dt = Math.min(.1, (now - last) / 1000); last = now;
      const goal = live.current.target.flow ? live.current.target.flow() : live.current.target;
      const k = 1 - Math.exp(-dt * 1.8);
      const want = goal.tones.map(rgb);
      cur.tones = cur.tones.map((c, i) => c.map((v, j) => v + (want[i][j] - v) * k));
      cur.dark += (goal.dark - cur.dark) * (1 - Math.exp(-dt * 2.0));
      cur.reach += (goal.reach - cur.reach) * (1 - Math.exp(-dt * 1.6));
      const rect = originRef?.current?.getBoundingClientRect();
      if (rect && rect.width) {
        const tx = (rect.left + rect.width * .5) / width;
        const ty = 1 - (rect.top + rect.height * .58) / height;
        const ko = 1 - Math.exp(-dt * 8);
        cur.ox += (tx - cur.ox) * ko; cur.oy += (Math.min(.85, Math.max(.15, ty)) - cur.oy) * ko;
      }
      const since = s => (s ? (now - s) / 1000 : 99);
      gl.uniform2f(U.uRes, canvas.width, canvas.height);
      gl.uniform1f(U.uTime, reduce.matches ? 12 : now / 1000);
      gl.uniform3fv(U.uA, cur.tones[0]); gl.uniform3fv(U.uB, cur.tones[1]); gl.uniform3fv(U.uC, cur.tones[2]);
      gl.uniform2f(U.uOrigin, cur.ox, cur.oy);
      gl.uniform1f(U.uDark, cur.dark);
      gl.uniform1f(U.uReach, cur.reach);
      gl.uniform1f(U.uRipple, reduce.matches ? 0 : Math.min(1.001, since(live.current.rippleAt) / 2.4));
      gl.uniform1f(U.uFlash, reduce.matches ? 0 : Math.min(1.001, since(live.current.flashAt) / 1.5));
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      frame = requestAnimationFrame(draw);
    }
    frame = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [originRef]);

  return <canvas className="backdrop" ref={canvasRef} aria-hidden="true" />;
}
