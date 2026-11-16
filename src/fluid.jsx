import React, { useEffect, useRef } from 'react';

const paper = [245, 241, 232];
const ink = [29, 31, 36];
const white = [255, 255, 255];
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const ease = t => 1 - (1 - t) ** 3;
const rgb = hex => [1, 3, 5].map(i => Number.parseInt(hex.slice(i, i + 2), 16));
const mix = (a, b, t) => a.map((value, i) => value + (b[i] - value) * t);
const color = (c, a = 1) => `rgba(${c.map(Math.round).join(',')},${a})`;

export function mixHex(first, last, amount) {
  return '#' + mix(rgb(first), rgb(last), amount).map(n => Math.round(n).toString(16).padStart(2, '0')).join('');
}

function useCanvas(draw) {
  const canvasRef = useRef(null);
  const drawRef = useRef(draw);
  drawRef.current = draw;
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let width = 0, height = 0, frame = 0;
    function render(time) {
      if (width && height) drawRef.current(ctx, width, height, time, motion.matches);
      if (!motion.matches) frame = requestAnimationFrame(render);
    }
    function refresh() {
      cancelAnimationFrame(frame);
      const ratio = Math.min(devicePixelRatio, 1.5);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      render(performance.now());
    }
    const observer = new ResizeObserver(refresh);
    observer.observe(canvas);
    motion.addEventListener('change', refresh);
    return () => {
      observer.disconnect();
      motion.removeEventListener('change', refresh);
      cancelAnimationFrame(frame);
    };
  }, []);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas?.width && matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const ctx = canvas.getContext('2d');
      if (ctx) draw(ctx, canvas.clientWidth, canvas.clientHeight, performance.now(), true);
    }
  }, [draw]);
  return canvasRef;
}

function gradientSpot(ctx, x, y, rx, ry, stops) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(Math.max(rx, 1), Math.max(ry, 1));
  const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
  for (const [at, c] of stops) gradient.addColorStop(at, c);
  ctx.fillStyle = gradient;
  ctx.fillRect(-1, -1, 2, 2);
  ctx.restore();
}

function surfacePath(ctx, width, count, heightAt) {
  ctx.beginPath();
  for (let i = 0; i <= count; i++) {
    const x = i / count * width;
    if (i === 0) ctx.moveTo(x, heightAt(x));
    else ctx.lineTo(x, heightAt(x));
  }
}


// 병 속 액체. level(0~100)과 색을 부드럽게 따라가므로 스크롤로 직접 움직여도 끊기지 않는다.
// 아래부터 베이스 → 미들 → 탑 색이 층을 이루고, 수위가 빠르게 변하거나 pulse가 바뀌면 수면이 출렁인다.
export function Liquid({ tones, level, pulse, accents }) {
  const state = useRef(null);
  const accentRgb = (accents ?? []).map(layer => layer.map(rgb));
  const canvas = useCanvas((ctx, w, h, now, still) => {
    const target = tones.map(rgb);
    if (!state.current) state.current = { fill: level / 100, colors: target, last: now, pulse, kick: -99, tilt: 0, vel: 0 };
    const s = state.current;
    const dt = Math.min(.1, (now - s.last) / 1000); s.last = now;
    if (s.pulse !== pulse) { s.pulse = pulse; s.kick = now; }
    const goal = level / 100;
    const before = s.fill;
    s.fill = still ? goal : s.fill + (goal - s.fill) * (1 - Math.exp(-dt * 2.4));
    s.colors = still ? target : s.colors.map((c, i) => mix(c, target[i], 1 - Math.exp(-dt * 2.8)));
    // 수위 변화 속도가 수면 기울기로 이어진다
    s.vel = dt ? (s.fill - before) / dt : 0;
    s.tilt += (clamp(s.vel * 3.2, -.5, .5) - s.tilt) * (1 - Math.exp(-dt * 5));
    ctx.clearRect(0, 0, w, h);
    const fill = s.fill;
    if (fill < .004) return;
    const [top, heart, base] = s.colors;
    const t = still ? 0 : now / 1000;
    const rest = h * (1 - fill);
    const since = (now - s.kick) / 1000;
    const impact = still ? 0 : Math.sin(since * 7.4) * Math.exp(-since * 1.5);
    const amplitude = h * Math.min(.024, fill * .2) * (1 + Math.abs(s.tilt) * 2);
    const heightAt = x => {
      const u = x / w;
      return rest + amplitude * (.55 * Math.sin(u * 7.2 + t * 1.4) + .32 * Math.sin(u * 13.1 - t * 1.9) + .16 * Math.sin(u * 23 + t * 2.7))
        + h * (impact * .028 + s.tilt * .05) * (u - .5) * 2;
    };
    ctx.save();
    surfacePath(ctx, w, 64, heightAt);
    ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
    ctx.clip();
    // 층: 위(탑) → 아래(베이스)
    const body = ctx.createLinearGradient(0, rest, 0, h);
    body.addColorStop(0, color(mix(top, white, .18), .62));
    body.addColorStop(.3, color(top, .74));
    body.addColorStop(.48, color(heart, .8));
    body.addColorStop(.7, color(heart, .84));
    body.addColorStop(.86, color(base, .9));
    body.addColorStop(1, color(mix(base, ink, .18), .95));
    ctx.fillStyle = body;
    ctx.fillRect(0, 0, w, h);
    // 한 층에 여러 노트가 있으면 각 색이 그 층 안에서 천천히 소용돌이치며 섞인다
    const centers = [.2, .56, .86];
    accentRgb.forEach((layer, li) => {
      if (layer.length < 2) return;
      const cy = rest + (h - rest) * centers[li];
      const band = (h - rest) * .2 + h * .03;
      layer.forEach((c, j) => {
        const phase = t * (.22 + j * .07) + j * 2.4 + li * 1.3;
        const cx = w * (.5 + Math.sin(phase) * .34);
        const yy = cy + Math.cos(phase * 1.3) * band * .35;
        gradientSpot(ctx, cx, yy, w * (.42 + .08 * Math.sin(phase * .7)), band, [
          [0, color(c, .62)], [.55, color(c, .3)], [1, color(c, 0)],
        ]);
      });
    });
    // 층 경계가 천천히 흔들리며 섞이는 느낌
    for (let band = 0; band < 2; band++) {
      const y0 = rest + (h - rest) * (.4 + band * .32);
      ctx.beginPath();
      for (let i = 0; i <= 48; i++) {
        const x = i / 48 * w;
        const y = y0 + Math.sin(i / 48 * 6 + t * (.6 + band * .3) + band * 2) * h * .012;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = color(mix(band ? heart : top, white, .5), .16);
      ctx.lineWidth = h * .03;
      ctx.filter = 'blur(6px)';
      ctx.stroke();
      ctx.filter = 'none';
    }
    ctx.globalCompositeOperation = 'screen';
    // 안쪽에서 떠도는 빛(커스틱)
    for (let i = 0; i < 3; i++) {
      const cx = w * (.5 + Math.sin(t * (.35 + i * .17) + i * 2.1) * .3);
      const cy = rest + (h - rest) * (.25 + i * .22 + Math.sin(t * .5 + i) * .05);
      gradientSpot(ctx, cx, cy, w * (.32 - i * .05), (h - rest) * .09 + h * .02, [
        [0, color(mix(top, white, .7), .34 - i * .07)], [1, color(top, 0)],
      ]);
    }
    // 유리 양옆에 비치는 굴절광
    const side = ctx.createLinearGradient(0, 0, w, 0);
    side.addColorStop(0, color(white, .32));
    side.addColorStop(.09, color(top, .14));
    side.addColorStop(.2, color(white, 0));
    side.addColorStop(.8, color(white, 0));
    side.addColorStop(.92, color(mix(top, white, .4), .22));
    side.addColorStop(1, color(white, .4));
    ctx.fillStyle = side;
    ctx.fillRect(0, 0, w, h);
    ctx.restore();
    // 수면(메니스커스): 밝은 선 + 아래 얇은 그림자
    const glint = ctx.createLinearGradient(0, 0, w, 0);
    glint.addColorStop(0, color(white, .2));
    glint.addColorStop(.35, color(white, .95));
    glint.addColorStop(.6, color(mix(top, white, .5), .8));
    glint.addColorStop(1, color(white, .25));
    surfacePath(ctx, w, 64, heightAt);
    ctx.strokeStyle = glint; ctx.lineWidth = Math.max(1.4, h * .005); ctx.stroke();
    surfacePath(ctx, w, 64, x => heightAt(x) + Math.max(2, h * .012));
    ctx.strokeStyle = color(mix(heart, ink, .3), .18); ctx.lineWidth = Math.max(1, h * .006); ctx.stroke();
  });
  return <canvas className="liquid-canvas" ref={canvas} aria-hidden="true" />;
}
