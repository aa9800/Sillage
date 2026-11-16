// 세련된 효과음: 실제 녹음(Freesound CC0)을 Web Audio로 다듬어 아주 작게 재생한다.
// 기본은 꺼짐. 켜면 그때 파일을 불러온다(브라우저 자동재생 정책상 사용자 클릭 뒤에만 소리가 난다).

const FILES = { clink: '/sounds/clink.mp3', swell: '/sounds/swell.mp3', drop: '/sounds/drop.mp3', pour: '/sounds/pour.mp3' };
const KEY = 'sillage-sound';
let ctx = null, master = null, buffers = {}, loading = null;
let enabled = false;
const listeners = new Set();

try { enabled = localStorage.getItem(KEY) === 'on'; } catch { enabled = false; }

function ensure() {
  if (!ctx) {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    master = ctx.createGain();
    master.gain.value = .9;
    // 아주 약한 고역 정리: 날카로운 끝을 부드럽게
    const tone = ctx.createBiquadFilter();
    tone.type = 'highshelf'; tone.frequency.value = 7000; tone.gain.value = -4;
    master.connect(tone).connect(ctx.destination);
  }
  if (ctx.state === 'suspended') ctx.resume();
  if (!loading) {
    loading = Promise.all(Object.entries(FILES).map(async ([name, url]) => {
      const data = await (await fetch(url)).arrayBuffer();
      buffers[name] = await ctx.decodeAudioData(data);
    })).catch(() => {});
  }
  return loading;
}

function play(name, { rate = 1, gain = .3, offset = 0, duration, fadeIn = .004, fadeOut = .25, delay = 0 } = {}) {
  if (!enabled) return;
  ensure().then(() => {
    const buffer = buffers[name];
    if (!buffer) return;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.playbackRate.value = rate;
    const g = ctx.createGain();
    const t0 = ctx.currentTime + .01 + delay;
    const length = Math.min(duration ?? buffer.duration - offset, buffer.duration - offset) / rate;
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(gain, t0 + fadeIn);
    g.gain.setValueAtTime(gain, Math.max(t0 + fadeIn, t0 + length - fadeOut));
    g.gain.exponentialRampToValueAtTime(.0001, t0 + length);
    src.connect(g).connect(master);
    src.start(t0, offset, length * rate);
  });
}

export const sound = {
  get enabled() { return enabled; },
  toggle() {
    enabled = !enabled;
    try { localStorage.setItem(KEY, enabled ? 'on' : 'off'); } catch { /* 저장 못 해도 동작 */ }
    if (enabled) { ensure().then(() => play('clink', { gain: .22, rate: 1.12 })); }
    listeners.forEach(fn => fn(enabled));
  },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  // 노트 고르기: 탑은 밝게, 베이스로 갈수록 조금 낮게
  select(stageIndex = 0) { play('clink', { rate: [1.06, .94, .84][stageIndex] ?? 1, gain: .28, duration: 1.1, fadeOut: .5 }); },
  deselect() { play('clink', { rate: .72, gain: .12, duration: .6, fadeOut: .4 }); },
  // 상담 화면으로 들어갈 때 길게 번지는 크리스털 울림
  enter() { play('swell', { gain: .42, duration: 3.2, fadeIn: .08, fadeOut: 1.4 }); },
  // AI 추천이 도착했을 때 물방울 하나
  arrive() { play('drop', { gain: .3, offset: .38, duration: .3, fadeOut: .15 }); },
  // 대화로 노트가 바뀌어 병이 다시 차오를 때
  pour() { play('pour', { gain: .2, offset: 1.0, duration: 1.3, fadeIn: .15, fadeOut: .7 }); },
};
