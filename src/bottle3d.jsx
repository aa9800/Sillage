import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

// 실제 3D로 그리는 향수병. 병마다 옆모습 윤곽(profile)을 회전시켜 몸통을 만들고,
// 둘레를 몇 면으로 나누느냐로 성격을 낸다(4면 = 사각, 8면 = 보석처럼 각진, 64면 = 둥근).
// 유리는 스튜디오 조명(RoomEnvironment)을 비추고 가장자리에 빛이 맺히며, 안의 액체는 탑·미들·베이스 색이 층을 이룬다.

// 윤곽은 [반지름, 높이] 점들. neck = 어깨가 끝나고 목이 시작되는 높이(액체는 여기까지만 찬다).
export const DESIGNS = {
  crystal: {  // 길고 각진 보석형, 크리스털 마개
    sides: 8, phase: Math.PI / 8, neck: 1.42,
    profile: [[0, 0], [.26, 0], [.31, .05], [.52, .72], [.34, 1.42], [.15, 1.7], [.12, 1.74], [.12, 1.86]],
    cap: { kind: 'gem', radius: .2, height: .5, y: 1.86, metal: null },
    collar: { radius: .14, height: .07, y: 1.82, metal: 'silver' },
  },
  ribbon: {  // 둥글고 넉넉한 플라스크, 금빛 마개와 리본 고리
    sides: 72, phase: 0, neck: 1.0,
    profile: [[0, 0], [.48, 0], [.56, .03], [.74, .18], [.8, .5], [.73, .84], [.46, 1.02], [.2, 1.1], [.18, 1.13], [.18, 1.24]],
    cap: { kind: 'cylinder', radius: .27, height: .3, y: 1.24, metal: 'gold' },
    ribbon: { radius: .2, tube: .035, y: 1.2, metal: 'gold' },
  },
  column: {  // 길쭉한 기둥, 둥근 은색 마개
    sides: 64, phase: 0, neck: 1.6,
    profile: [[0, 0], [.3, 0], [.35, .04], [.35, 1.58], [.29, 1.7], [.13, 1.76], [.13, 1.86]],
    cap: { kind: 'dome', radius: .2, height: .26, y: 1.86, metal: 'silver' },
  },
  emerald: {  // 사각(4면) 병, 검은 유광 마개
    sides: 4, phase: Math.PI / 4, neck: 1.16,
    profile: [[0, 0], [.78, 0], [.86, .06], [.86, 1.12], [.76, 1.22], [.26, 1.3], [.24, 1.33], [.24, 1.42]],
    cap: { kind: 'box', radius: .36, height: .42, y: 1.42, metal: 'black' },
  },
  oval: {  // 둥근 타원 병, 사각 은색 마개
    sides: 72, phase: 0, neck: 1.18,
    profile: [[0, 0], [.42, 0], [.52, .04], [.68, .3], [.72, .62], [.66, .98], [.48, 1.2], [.22, 1.3], [.17, 1.33], [.17, 1.46]],
    cap: { kind: 'box', radius: .34, height: .34, y: 1.46, metal: 'silver' },
  },
};

// 빛만 더하는 섞기: 색은 더하고(하이라이트), 캔버스의 투명도는 그대로 둔다 → 반사가 없는 곳은 배경이 그대로 비친다
const ADD_LIGHT = {
  blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
  blendSrc: THREE.SrcAlphaFactor, blendDst: THREE.OneFactor,
  blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor,
};

const METALS = {
  silver: { color: 0xe4e6ea, metalness: 1, roughness: .32 },
  gold: { color: 0xe2bd74, metalness: 1, roughness: .34 },
  black: { color: 0x141414, metalness: .3, roughness: .12, clearcoat: 1 },
};

const liquidVertex = /* glsl */`
varying vec3 vPos; varying vec3 vNormal; varying vec3 vView;
void main() {
  vPos = position;
  vec4 world = modelMatrix * vec4(position, 1.0);
  vNormal = normalize(mat3(modelMatrix) * normal);
  vView = normalize(cameraPosition - world.xyz);
  gl_Position = projectionMatrix * viewMatrix * world;
}`;

// 액체: 높이에 따라 베이스(아래) → 미들 → 탑(위) 색이 부드럽게 바뀌고, 수면은 찰랑인다.
// 안쪽 면(gl_FrontFacing이 아님)은 수면처럼 보이게 탑 색을 밝게 칠한다.
const liquidFragment = /* glsl */`
uniform vec3 uC0; uniform vec3 uC1; uniform vec3 uC2;
uniform float uLevel; uniform float uBottom; uniform float uTime; uniform float uWobble;
varying vec3 vPos; varying vec3 vNormal; varying vec3 vView;
void main() {
  float wave = (sin(vPos.x * 7.0 + uTime * 1.7) * .011 + sin(vPos.z * 6.0 - uTime * 1.3) * .009) * (1.0 + uWobble * 4.0);
  float top = uBottom + uLevel;
  if (vPos.y > top + wave) discard;
  float h = clamp((vPos.y - uBottom) / max(uLevel, .001), 0.0, 1.0);
  vec3 col = mix(uC2, uC1, smoothstep(.26, .44, h));
  col = mix(col, uC0, smoothstep(.6, .78, h));
  if (!gl_FrontFacing) {
    col *= .78;
  } else {
    float fres = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.2);
    col = mix(col, col * .62, fres * .7);
    col += vec3(.05) * smoothstep(.85, 1.0, h);
  }
  gl_FragColor = vec4(col, .86);
  #include <colorspace_fragment>
}`;

// 수면: 탑 색을 밝게, 가장자리로 갈수록 살짝 진하게
const surfaceFragment = /* glsl */`
uniform vec3 uC0;
varying vec3 vPos; varying vec3 vNormal; varying vec3 vView;
void main() {
  float r = length(vPos.xz);
  vec3 col = mix(uC0, vec3(1.0), .22) * (1.0 - r * .25);
  gl_FragColor = vec4(col, .9);
  #include <colorspace_fragment>
}`;

// 윤곽에서 높이 y의 반지름(점 사이를 선형으로)
function radiusAt(profile, y) {
  for (let i = 1; i < profile.length; i++) {
    const [r0, y0] = profile[i - 1], [r1, y1] = profile[i];
    if (y <= y1 && y1 > y0) return r0 + (r1 - r0) * Math.max(0, (y - y0) / (y1 - y0));
  }
  return profile[profile.length - 1][0];
}

// 유리 가장자리의 그늘: 밝은 배경 앞에서도 병 윤곽이 보이게(실제 유리처럼 가장자리가 어둡게 꺾여 보임)
const edgeFragment = /* glsl */`
varying vec3 vPos; varying vec3 vNormal; varying vec3 vView;
void main() {
  float fres = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.4);
  gl_FragColor = vec4(vec3(.17, .15, .13), fres * .38);
}`;

// 유리 가장자리의 빛: 시선과 비스듬한 면일수록 밝게(프레넬)
const rimFragment = /* glsl */`
varying vec3 vPos; varying vec3 vNormal; varying vec3 vView;
void main() {
  float fres = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 3.0);
  gl_FragColor = vec4(vec3(1.0), fres * .12);
}`;

function lathe(points, sides, phase, scale = 1, lift = 0) {
  const pts = points.map(([r, y]) => new THREE.Vector2(r * scale, y + lift));
  const geo = new THREE.LatheGeometry(pts, sides, phase);
  if (sides <= 8) {
    // 면이 적은 병은 각 면이 평평하게 보이도록 노멀을 면마다 따로 계산
    const flat = geo.toNonIndexed();
    flat.computeVertexNormals();
    geo.dispose();
    return flat;
  }
  geo.computeVertexNormals();
  return geo;
}

function makeCap(spec) {
  const group = new THREE.Group();
  const metal = spec.metal ? new THREE.MeshPhysicalMaterial({ ...METALS[spec.metal], envMapIntensity: 2.6 }) : null;
  let mesh;
  if (spec.kind === 'gem') {
    const glass = new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: .02, metalness: 0, transparent: true, opacity: .55,
      clearcoat: 1, envMapIntensity: 2.2, flatShading: true });
    const geo = new THREE.LatheGeometry([[0, 0], [spec.radius * .55, 0], [spec.radius, spec.height * .38], [spec.radius * .4, spec.height * .9], [0, spec.height]]
      .map(([r, y]) => new THREE.Vector2(r, y)), 6, Math.PI / 6);
    mesh = new THREE.Mesh(geo, glass);
  } else if (spec.kind === 'dome') {
    const geo = new THREE.SphereGeometry(spec.radius, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2);
    geo.scale(1, spec.height / spec.radius, 1);
    mesh = new THREE.Mesh(geo, metal);
  } else if (spec.kind === 'box') {
    const geo = new THREE.BoxGeometry(spec.radius * 2, spec.height, spec.radius * 1.3, 1, 1, 1);
    geo.translate(0, spec.height / 2, 0);
    mesh = new THREE.Mesh(geo, metal);
  } else {
    const geo = new THREE.CylinderGeometry(spec.radius, spec.radius, spec.height, 64);
    geo.translate(0, spec.height / 2, 0);
    mesh = new THREE.Mesh(geo, metal);
  }
  mesh.position.y = spec.y;
  group.add(mesh);
  return group;
}

// 사진 스튜디오 같은 조명 환경: 어두운 공간에 세로로 긴 소프트박스 2개와 위쪽 띠 조명 하나.
// 유리는 이 조명만 또렷한 하이라이트로 비추고, 나머지는 투명하게 남는다.
function studioEnvironment() {
  const env = new THREE.Scene();
  env.background = new THREE.Color(0x1c1b1a);
  const panel = (w, h, x, y, z, ry, strength = 1) => {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(strength, strength, strength * .97), side: THREE.DoubleSide }));
    mesh.position.set(x, y, z); mesh.rotation.y = ry; mesh.lookAt(0, 0, 0);
    env.add(mesh);
  };
  panel(1.4, 6, -4.5, .5, 2.5, 0, 2.6);   // 왼쪽 앞 소프트박스(주광)
  panel(1.0, 6, 4.8, .2, 1.2, 0, 1.4);    // 오른쪽 보조광
  panel(6, .7, 0, 4.6, 1.5, 0, .9);       // 위쪽 띠 조명
  panel(3, 3, 0, 1, -5, 0, .5);           // 뒤쪽 은은한 반사판
  panel(2.6, 2.2, -2.2, 2.4, 7, 0, 1.1);  // 카메라 뒤 위쪽 보조판(마개 정면이 너무 어둡지 않게)
  return env;
}

export function canUse3D() {
  try {
    if (new URLSearchParams(location.search).get('flat') === '1') return false;
    const c = document.createElement('canvas');
    return Boolean(c.getContext('webgl2') || c.getContext('webgl'));
  } catch { return false; }
}

export function Bottle3D({ design, tones, level, pulse, onFail }) {
  const host = useRef(null);
  const live = useRef({ tones, level, pulseAt: 0 });
  live.current.tones = tones;
  live.current.level = level;
  useEffect(() => { live.current.pulseAt = performance.now(); }, [pulse]);

  useEffect(() => {
    const el = host.current;
    const spec = DESIGNS[design] ?? DESIGNS.oval;
    let renderer;
    try {
      // preserveDrawingBuffer: 결과 카드를 만들 때 지금 그림을 그대로 옮겨 담기 위해
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
    } catch (error) {
      console.warn('3D bottle unavailable', error);
      onFail?.();
      return undefined;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = .95;
    renderer.domElement.className = 'bottle3d';
    el.append(renderer.domElement);

    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    const env = pmrem.fromScene(studioEnvironment(), .02).texture;
    scene.environment = env;
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(2, 3, 4);
    scene.add(key, new THREE.AmbientLight(0xffffff, .35));

    const bottle = new THREE.Group();
    scene.add(bottle);
    const height = Math.max(...spec.profile.map(([, y]) => y));

    // 액체(유리 두께만큼 안쪽, 바닥은 조금 띄움)
    const body = spec.profile.filter(([, y]) => y <= spec.neck + .001);
    const liquidGeo = lathe(body, spec.sides, spec.phase, .88, .05);
    const uniforms = {
      uC0: { value: new THREE.Color() }, uC1: { value: new THREE.Color() }, uC2: { value: new THREE.Color() },
      uLevel: { value: .1 }, uBottom: { value: .05 }, uTime: { value: 0 }, uWobble: { value: 0 },
    };
    const liquidBack = new THREE.Mesh(liquidGeo, new THREE.ShaderMaterial({ vertexShader: liquidVertex, fragmentShader: liquidFragment,
      uniforms, transparent: true, side: THREE.BackSide, depthWrite: false }));
    const liquid = new THREE.Mesh(liquidGeo, new THREE.ShaderMaterial({ vertexShader: liquidVertex, fragmentShader: liquidFragment,
      uniforms, transparent: true, side: THREE.FrontSide, depthWrite: false }));
    const surfaceGeo = new THREE.CircleGeometry(1, spec.sides, spec.phase);
    surfaceGeo.rotateX(-Math.PI / 2);
    const surface = new THREE.Mesh(surfaceGeo, new THREE.ShaderMaterial({ vertexShader: liquidVertex, fragmentShader: surfaceFragment,
      uniforms, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
    liquidBack.renderOrder = 1; surface.renderOrder = 1.5; liquid.renderOrder = 2;

    // 유리: 뒷면(안쪽 두께) → 앞면(반사) → 가장자리 빛 순서로 겹친다
    const glassGeo = lathe(spec.profile, spec.sides, spec.phase);
    const glassBack = new THREE.Mesh(glassGeo, new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: .08, transparent: true,
      opacity: .05, side: THREE.BackSide, envMapIntensity: .8, depthWrite: false }));
    const glassFront = new THREE.Mesh(glassGeo, new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: .05, metalness: 0,
      transparent: true, opacity: .05, envMapIntensity: .8, depthWrite: false }));
    // 반사 층: 바탕색은 검정이라 더해지지 않고, 조명이 비친 하이라이트만 밝게 더해진다
    const shine = new THREE.Mesh(glassGeo, new THREE.MeshPhysicalMaterial({ color: 0x000000, roughness: .04, metalness: 0,
      clearcoat: 1, clearcoatRoughness: .03, envMapIntensity: 2.3, transparent: true, ...ADD_LIGHT, depthWrite: false }));
    const rim = new THREE.Mesh(glassGeo, new THREE.ShaderMaterial({ vertexShader: liquidVertex, fragmentShader: rimFragment,
      transparent: true, depthWrite: false, ...ADD_LIGHT }));
    const edge = new THREE.Mesh(glassGeo, new THREE.ShaderMaterial({ vertexShader: liquidVertex, fragmentShader: edgeFragment,
      transparent: true, depthWrite: false }));
    glassBack.renderOrder = 0; glassFront.renderOrder = 3; edge.renderOrder = 3.5; shine.renderOrder = 4; rim.renderOrder = 5;
    bottle.add(glassBack, liquidBack, surface, liquid, glassFront, edge, shine, rim);

    if (spec.collar) {
      const collar = new THREE.Mesh(new THREE.CylinderGeometry(spec.collar.radius, spec.collar.radius, spec.collar.height, 48),
        new THREE.MeshPhysicalMaterial({ ...METALS[spec.collar.metal], envMapIntensity: 2.6 }));
      collar.position.y = spec.collar.y;
      bottle.add(collar);
    }
    if (spec.ribbon) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(spec.ribbon.radius, spec.ribbon.tube, 16, 64),
        new THREE.MeshPhysicalMaterial({ ...METALS[spec.ribbon.metal], envMapIntensity: 2.6 }));
      ring.rotation.x = Math.PI / 2;
      ring.position.y = spec.ribbon.y;
      bottle.add(ring);
    }
    const cap = makeCap(spec.cap);
    bottle.add(cap);
    const total = Math.max(height, spec.cap.y + spec.cap.height);
    bottle.position.y = -total / 2;

    const camera = new THREE.PerspectiveCamera(24, 1, .1, 50);
    const widest = Math.max(...spec.profile.map(([r]) => r), spec.cap.radius) * 2 * 1.08;
    function resize() {
      const w = el.clientWidth || 1, h = el.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // 높이와 폭이 모두 들어오도록 카메라 거리를 정한다
      const fitH = (total * 1.06 / 2) / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
      const fitW = (widest / 2) / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / camera.aspect;
      camera.position.set(0, total * .02, Math.max(fitH, fitW) + .4);
      camera.lookAt(0, 0, 0);
      camera.updateProjectionMatrix();
    }
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();

    const reduce = matchMedia('(prefers-reduced-motion: reduce)');
    const css = document.documentElement.style;
    const maxLevel = spec.neck - .05;
    const target = [new THREE.Color(), new THREE.Color(), new THREE.Color()];
    let frame = 0, last = performance.now(), level = 0, spin = 0;
    function draw(now) {
      const dt = Math.min(.1, (now - last) / 1000); last = now;
      const t = now / 1000;
      const k = 1 - Math.exp(-dt * 2.4);
      live.current.tones.forEach((hex, i) => target[i].set(hex));
      [uniforms.uC0, uniforms.uC1, uniforms.uC2].forEach((u, i) => u.value.lerp(target[i], k));
      level += (Math.max(.08, live.current.level / 100) - level) * (1 - Math.exp(-dt * 2));
      uniforms.uLevel.value = maxLevel * level;
      const surfaceY = .05 + maxLevel * level;
      const surfaceR = radiusAt(body, surfaceY - .05) * .88 * .985;
      surface.position.y = surfaceY;
      surface.scale.set(surfaceR, 1, surfaceR);
      uniforms.uTime.value = reduce.matches ? 0 : t;
      const since = (now - live.current.pulseAt) / 1000;
      uniforms.uWobble.value = reduce.matches ? 0 : Math.max(0, 1 - since / 1.4);
      // 마우스·스크롤 기울기(App이 --tilt-x/y를 갱신) + 아주 느린 자체 회전
      const tx = Number.parseFloat(css.getPropertyValue('--tilt-x')) || 0;
      const ty = Number.parseFloat(css.getPropertyValue('--tilt-y')) || 0;
      if (!reduce.matches) spin += dt * .12;
      bottle.rotation.y = tx * .75 + Math.sin(spin) * .22;
      bottle.rotation.x = ty * .14;
      bottle.position.y = -total / 2 + (reduce.matches ? 0 : Math.sin(t * .6) * .025);
      renderer.render(scene, camera);
      frame = requestAnimationFrame(draw);
    }
    frame = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      scene.traverse(obj => {
        obj.geometry?.dispose?.();
        const mats = Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : [];
        mats.forEach(m => m.dispose());
      });
      env.dispose(); pmrem.dispose(); renderer.dispose();
      renderer.domElement.remove();
    };
  }, [design]);

  return <div className="bottle3d-host" ref={host} />;
}
