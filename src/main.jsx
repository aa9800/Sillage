import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';
import { Button } from '@astryxdesign/core/Button';
import { TextInput } from '@astryxdesign/core/TextInput';
import { Theme } from '@astryxdesign/core/theme';
import { neutralTheme } from '@astryxdesign/theme-neutral/built';
import '@astryxdesign/core/astryx.css';
import '@astryxdesign/theme-neutral/theme.css';
import { Liquid, mixHex } from './fluid';
import { Backdrop } from './backdrop';
import { NoteIcon } from './note-icons';
import { blendColors, mixColors } from './color';
import { sound } from './sound';
import entranceMotion from './entrance-motion';
import notesCatalog from '../blend-notes.json';
import './sillage.css';

gsap.registerPlugin(ScrollTrigger);

const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// 사용자가 화면에서 넣은 OpenAI 키. 이 브라우저 탭에만(sessionStorage) 보관하고, 우리 서버를 거쳐 OpenAI 호출에만 쓴다.
const KEY_STORE = 'sillage-openai-key';
const readKey = () => { try { return sessionStorage.getItem(KEY_STORE) || ''; } catch { return ''; } };
function api(url, options = {}) {
  const key = readKey();
  const headers = { ...(options.headers || {}), ...(key ? { 'X-OpenAI-Key': key } : {}) };
  return fetch(url, { ...options, headers });
}
// 저장한 향수(취향 기억). 이 브라우저에만(localStorage) 보관하고, 상담과 추천에 id만 보낸다.
const LIKED_STORE = 'sillage-liked';
const readLiked = () => { try { const list = JSON.parse(localStorage.getItem(LIKED_STORE) || '[]'); return Array.isArray(list) ? list : []; } catch { return []; } };
const writeLiked = list => { try { localStorage.setItem(LIKED_STORE, JSON.stringify(list)); } catch { /* 저장 못 해도 화면에는 반영 */ } };
const HINT_STORE = 'sillage-sound-hint';
const hintSeen = () => { try { return localStorage.getItem(HINT_STORE) === '1'; } catch { return true; } };
const byId = Object.fromEntries(notesCatalog.map(note => [note.id, note]));
const MAX_PER_STAGE = 3;

/* ───────── 데이터 ───────── */

const welcome = { role: 'assistant', content: '어떤 향을 찾고 계세요? 좋아하는 노트나, 향으로 기억하고 싶은 장면을 들려주세요.' };
const examples = ['비 온 뒤 숲, 달지 않게', '오늘 서울 날씨에 맞는 향', '탐다오 같은 향으로 만들어 줘', '상탈 33이랑 어나더 13 비교해 줘', '햇볕에 마른 셔츠'];
const startingPalette = { base: '#8c806c', highlight: '#f4e8d0', shadow: '#5b6360', family: 'violet', label: '향을 기다리는 중' };
const empty = { palette: startingPalette, notes: [], products: [], level: 0, ready: false };
const noSelection = { top: [], heart: [], base: [] };
const stages = [
  { id: 'top', no: '01', label: '탑 노트', en: 'Top', detail: '처음 맡았을 때 느껴지는 향' },
  { id: 'heart', no: '02', label: '미들 노트', en: 'Heart', detail: '잠시 뒤 드러나는 향의 중심' },
  { id: 'base', no: '03', label: '베이스 노트', en: 'Base', detail: '마지막까지 남는 잔향' },
];

// 장마다 병 속 액체와 배경 색, 어두움, 색이 퍼지는 범위, 수위, 병 위치
const scenes = {
  hero: { tones: ['#f2e6c9', '#cdb68a', '#8c7556'], dark: 0, reach: .5, level: 22, shift: 0 },
  intro: { tones: ['#f6ecd8', '#dcc6a2', '#9c8263'], dark: 0, reach: .8, level: 30, shift: 0 },
  top: { tones: ['#f4f1a2', '#bcd56b', '#6f913b'], dark: 0, reach: 1.05, level: 44, shift: 0 },
  heart: { tones: ['#ffdfe0', '#e8a0ae', '#a2587d'], dark: 0, reach: 1.1, level: 64, shift: 0 },
  base: { tones: ['#f7dcab', '#c38c5b', '#6c4630'], dark: 0, reach: 1.15, level: 84, shift: 0 },
  families: { tones: ['#f8e6c8', '#e3ad97', '#8b7aa8'], dark: 0, reach: 1.25, level: 84, shift: 0 },
  materials: { tones: ['#f3e3b5', '#c9a163', '#5d4128'], dark: 1, reach: .9, level: 84, shift: 0 },
  strengths: { tones: ['#e4e6f6', '#a0a8d8', '#505a95'], dark: 1, reach: .85, level: 84, shift: -1 },
  testing: { tones: ['#eef1e4', '#bccab0', '#61806e'], dark: 0, reach: 1, level: 84, shift: 0 },
  begin: { tones: ['#f4e9cf', '#d6bb8b', '#8d704f'], dark: 0, reach: 1.4, level: 84, shift: 0 },
};

// 스크롤에 따라 배경색이 다음 장으로 천천히 이어지게 한다.
// 화면 55% 높이선이 지나는 장을 찾고, 그 장의 뒤쪽 절반 동안 다음 장의 색으로 OKLab에서 섞는다.
const smooth = t => t * t * (3 - 2 * t);
function storyFlow() {
  const sections = document.querySelectorAll('.entrance [data-chapter]');
  if (!sections.length) return scenes.hero;
  const line = innerHeight * .55;
  let index = 0;
  sections.forEach((section, i) => { if (section.getBoundingClientRect().top <= line) index = i; });
  const box = sections[index].getBoundingClientRect();
  const here = scenes[sections[index].dataset.chapter] ?? scenes.hero;
  const next = scenes[sections[index + 1]?.dataset.chapter];
  if (!next) return here;
  const progress = Math.min(1, Math.max(0, (line - box.top) / Math.max(1, box.height)));
  const t = smooth(Math.min(1, Math.max(0, (progress - .45) / .55)));
  if (t <= 0) return here;
  return {
    tones: here.tones.map((tone, i) => mixColors(tone, next.tones[i], t)),
    dark: here.dark + (next.dark - here.dark) * t,
    reach: here.reach + (next.reach - here.reach) * t,
  };
}

const pyramid = [
  { id: 'top', name: 'Top', ko: '탑', time: '5–15분', text: '가볍고 빨리 날아가는 향' },
  { id: 'heart', name: 'Heart', ko: '미들', time: '몇 시간', text: '향수의 성격을 만드는 중심' },
  { id: 'base', name: 'Base', ko: '베이스', time: '반나절 이상', text: '무겁고 오래 남는 잔향' },
];

const noteChapters = [
  { id: 'top', no: '01', ko: '탑 노트', fr: 'Notes de tête', en: ['Top', <em key="e">Notes</em>], word: ['First', 'Light'], time: '뿌린 직후 · 보통 5–15분',
    body: '향수를 뿌리자마자 먼저 인사하는 향이에요. 가볍고 휘발이 빨라 금세 사라지지만, 그 향수를 기억하게 만드는 첫인상이 여기서 정해져요.',
    notes: ['lime', 'salt', 'fig-leaf', 'pear'] },
  { id: 'heart', no: '02', ko: '미들 노트', fr: 'Notes de cœur', en: ['Heart', <em key="e">Notes</em>], word: ['True', 'Heart'], time: '첫 향이 잦아든 뒤 · 몇 시간',
    body: '첫 향이 걷히면 향수의 성격이 드러나요. 꽃, 허브, 나무처럼 향의 이야기를 끌고 가는 노트들이 가장 오래 무대에 머물러요.',
    notes: ['freesia', 'sage', 'cypress', 'iris'] },
  { id: 'base', no: '03', ko: '베이스 노트', fr: 'Notes de fond', en: ['Base', <em key="e">Notes</em>], word: ['Last', 'Trace'], time: '시간이 흐른 뒤 · 반나절 이상',
    body: '피부 가까이에 마지막까지 남는 향이에요. 무겁고 천천히 퍼지는 노트가 앞선 향들을 받쳐 주고, 하루의 끝에 기억되는 잔향을 만들어요.',
    notes: ['sandalwood', 'musk', 'vanilla', 'patchouli'] },
];

const families = [
  { ko: '시트러스', en: 'Citrus', color: '#e8c547', text: '레몬·베르가못처럼 밝고 상큼한' },
  { ko: '그린', en: 'Green', color: '#8dbb63', text: '막 꺾은 풀잎의 싱그러움' },
  { ko: '아쿠아틱', en: 'Aquatic', color: '#67c0d3', text: '바닷바람처럼 투명한' },
  { ko: '플로럴', en: 'Floral', color: '#ee9fb8', text: '꽃다발처럼 화사한' },
  { ko: '머스크', en: 'Musk', color: '#b2a8d4', text: '살결처럼 포근한' },
  { ko: '앰버', en: 'Amber', color: '#d98a3d', text: '바닐라·수지의 달고 깊은' },
  { ko: '우디', en: 'Woody', color: '#a97c55', text: '마른 나무의 따뜻한 결' },
];

const materials = [
  { fr: 'Citron vert', ko: '라임', text: '껍질을 비틀었을 때 퍼지는 밝고 상큼한 시트러스', color: '#cfde71', icon: 'lime' },
  { fr: 'Freesia', ko: '프리지아', text: '막 피어난 꽃처럼 가볍고 맑은 플로럴', color: '#f4b9b8', icon: 'freesia' },
  { fr: 'Santal', ko: '샌달우드', text: '부드럽고 크리미한 결을 남기는 우디', color: '#c99167', icon: 'sandalwood' },
];

// 업계에서 흔히 쓰는 대략적인 부향률. 브랜드마다 기준이 다르다.
const strengths = [
  { ko: '오 드 코롱', en: 'Eau de Cologne', range: '약 2–5%', from: 2, to: 5, note: '샤워 뒤처럼 가볍고 짧게' },
  { ko: '오 드 뚜왈렛', en: 'Eau de Toilette', range: '약 5–15%', from: 5, to: 15, note: '산뜻하게 하루를 여는 농도' },
  { ko: '오 드 퍼퓸', en: 'Eau de Parfum', range: '약 15–20%', from: 15, to: 20, note: '향의 전개가 풍성하고 오래가는 편' },
  { ko: '퍼퓸', en: 'Parfum · Extrait', range: '약 20–30%', from: 20, to: 30, note: '가장 진하고 피부 가까이 머무는 농도' },
];

const testingSteps = [
  { title: '시향지로 먼저 좁히기', text: '여러 향을 시향지에 뿌려 마음에 드는 방향을 두세 개로 좁혀요.' },
  { title: '피부에서 확인하기', text: '손목 안쪽에 뿌리고 문지르지 않아요. 같은 향도 피부마다 조금씩 다르게 피어나요.' },
  { title: '시간을 두고 맡기', text: '첫 향만으로 고르지 말고, 30분 뒤와 몇 시간 뒤의 잔향까지 맡아봐요.' },
  { title: '한 번에 몇 개만', text: '코는 금방 무뎌져요. 한 번에 서너 개 정도만 비교하는 게 좋아요.' },
];

const liquidTones = {
  violet: ['#f4e8d0', '#c4b394', '#7d6f58'],
  forest: ['#62e1c1', '#298c66', '#15483f'],
  marine: ['#4fe8ff', '#357ac6', '#242a80'],
  amber: ['#fff0b2', '#e9983c', '#a03522'],
  floral: ['#ffcbe5', '#d85a97', '#672a85'],
  linen: ['#f1f4ff', '#aaa4ec', '#4d5c9f'],
  citrus: ['#fff7a2', '#e9b13c', '#648331'],
};
const idleLevel = 32;
const idleTones = ['#f4e8d0', '#c4b394', '#7d6f58'];
function liquidColors({ family, temperature }) {
  if (family === 'forest' && temperature === 'cool') return ['#69eced', '#249b91', '#1a416b'];
  if (family === 'forest' && temperature === 'warm') return ['#d4e08f', '#a19a49', '#a34e25'];
  const [surface, heart, depth] = liquidTones[family] ?? liquidTones.violet;
  return [
    surface,
    temperature === 'warm' && family !== 'amber' ? mixHex(heart, '#ffcb83', .24) : heart,
    temperature === 'cool' && family !== 'marine' ? mixHex(depth, '#29296d', .24) : depth,
  ];
}
// 서버가 보낸 선택(문자열 또는 배열)을 {top:[], heart:[], base:[]}로 맞춘다
function normalize(blend = {}) {
  return Object.fromEntries(stages.map(({ id }) => {
    const value = blend[id];
    return [id, (Array.isArray(value) ? value : value ? [value] : []).filter(n => byId[n]?.stage === id)];
  }));
}
const compact = selection => Object.fromEntries(Object.entries(selection).filter(([, ids]) => ids.length));
const countOf = selection => Object.values(selection).reduce((sum, ids) => sum + ids.length, 0);

const bottles = [
  { id: 'crystal', ratio: 596 / 1670, inset: '25.7% 8% 6.5%', mask: 'polygon(37% 0, 60% 0, 98% 52%, 71% 100%, 29% 100%, 0 52%)' },
  { id: 'ribbon', ratio: 448 / 637, inset: '38% 14% 14%', mask: 'polygon(29% 0, 71% 0, 92% 13%, 100% 32%, 86% 64%, 65% 98%, 55% 100%, 45% 100%, 35% 98%, 14% 64%, 0 32%, 8% 13%)' },
  { id: 'column', ratio: 247 / 637, inset: '23% 18% 12%', mask: 'inset(0 round 21% 21% 15% 15% / 9% 9% 5% 5%)' },
  { id: 'emerald', ratio: 499 / 577, inset: '33% 16% 14%', mask: 'polygon(8% 0, 92% 0, 100% 12%, 100% 88%, 92% 100%, 8% 100%, 0 88%, 0 12%)' },
  { id: 'oval', ratio: 404 / 602, inset: '27% 15% 14%', mask: 'inset(0 round 50% 50% 43% 43% / 45% 45% 57% 57%)' },
];
function chooseBottle() {
  try {
    const forced = new URLSearchParams(location.search).get('bottle');
    const pick = bottles.find(bottle => bottle.id === forced);
    if (pick) return pick;
    const previous = sessionStorage.getItem('sillage-bottle');
    const options = bottles.filter(bottle => bottle.id !== previous);
    const selected = options[Math.floor(Math.random() * options.length)];
    sessionStorage.setItem('sillage-bottle', selected.id);
    return selected;
  } catch {
    return bottles[Math.floor(Math.random() * bottles.length)];
  }
}

/* ───────── 병 ───────── */

function Vessel({ bottle, tones, level, pulse, origin, accents }) {
  const image = `/atelier/${bottle.id}.webp`;
  return <div className="vessel" ref={origin} style={{ '--ratio': bottle.ratio, '--t0': tones[0], '--t1': tones[1], '--t2': tones[2] }} aria-hidden="true">
    <div className="vessel-shadow" />
    <div className="bottle" data-vessel={bottle.id} style={{ '--vessel': `url(${image})`, '--fill': `${Math.max(8, level * .8)}%` }}>
      <img className="crystal" src={image} alt="" />
      <div className="liquid-chamber" style={{ inset: bottle.inset, clipPath: bottle.mask }}>
        <Liquid tones={tones} level={level} pulse={pulse} accents={accents} />
      </div>
      <div className="glass-tint" />
      <div className="crystal-light" />
    </div>
  </div>;
}

function StoryVessel({ bottle, chapter, opening, vesselRef }) {
  const glint = useRef(null);
  const scene = scenes[chapter];
  useEffect(() => {
    if (!opening || reduceMotion()) return;
    let animation, cancelled = false;
    import('lottie-web/build/player/lottie_light').then(({ default: lottie }) => {
      if (!cancelled) animation = lottie.loadAnimation({
        container: glint.current, renderer: 'svg', loop: false, autoplay: true, animationData: structuredClone(entranceMotion),
      });
    }).catch(() => {});
    return () => { cancelled = true; animation?.destroy(); };
  }, [opening]);
  return <div className="story-vessel" data-shift={scene.shift} data-dim={scene.dark} data-chapter-now={chapter} ref={vesselRef} style={{ '--ratio': bottle.ratio }}>
    <div className="story-vessel-shift"><div className="story-vessel-float">
      <Vessel bottle={bottle} tones={opening ? idleTones : scene.tones} level={opening ? idleLevel : scene.level} pulse={chapter} />
      <div className="story-glint" ref={glint} />
    </div></div>
  </div>;
}

/* ───────── 첫 화면 · 스크롤 스토리 ───────── */

function Lines({ lines, className = '' }) {
  return <span className={`lines ${className}`}>{lines.map((line, i) =>
    <span className="line" key={i}><span className="line-inner">{line}</span></span>)}</span>;
}

// sticky로 고정된 장의 공통 진입·퇴장: 제목 줄은 마스크 안에서 올라오고, 나머지는 살짝 떠오른다
function chapterTimeline(target, scrub = 1.2) {
  const section = typeof target === 'string' ? document.querySelector(target) : target;
  const tl = gsap.timeline({ scrollTrigger: { trigger: section, start: 'top top', end: 'bottom bottom', scrub } });
  const titleLines = section.querySelectorAll('.chapter-title .line-inner');
  const reveals = section.querySelectorAll('.reveal');
  tl.fromTo(titleLines, { yPercent: 108 }, { yPercent: 0, stagger: .03, duration: .18, ease: 'power3.out' }, .04)
    .fromTo(reveals, { opacity: 0, y: 34 }, { opacity: 1, y: 0, stagger: .025, duration: .18, ease: 'power2.out' }, .08)
    .to(titleLines, { yPercent: -108, stagger: .02, duration: .12, ease: 'power2.in' }, .86)
    .to(reveals, { opacity: 0, y: -26, stagger: .015, duration: .12, ease: 'power1.in' }, .84);
  return tl;
}

function Entrance({ opening, onChapter, onStart }) {
  const root = useRef(null);
  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      gsap.utils.toArray('[data-chapter]').forEach(section => {
        ScrollTrigger.create({
          trigger: section, start: 'top 55%', end: 'bottom 55%',
          onToggle: self => self.isActive && onChapter(section.dataset.chapter),
        });
      });
      if (reduceMotion()) return;
      // 첫 화면
      gsap.from('.hero .line-inner', { yPercent: 110, duration: 1.6, ease: 'expo.out', stagger: .12, delay: .2 });
      gsap.from('.hero .fade-in', { opacity: 0, y: 14, duration: 1.4, ease: 'power3.out', stagger: .1, delay: 1 });
      gsap.fromTo(document.querySelector('.story-vessel-float'), { yPercent: 92, scale: .86, opacity: 0 }, {
        yPercent: 0, scale: 1, opacity: 1, ease: 'none',
        scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom 15%', scrub: 1.4 },
      });
      gsap.timeline({ scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1.2 } })
        .to('.hero .hero-mark', { yPercent: -26, opacity: 0, ease: 'none' }, 0)
        .to('.hero .title .line:nth-child(1)', { xPercent: -12, ease: 'none' }, 0)
        .to('.hero .title .line:nth-child(2)', { xPercent: 10, ease: 'none' }, 0)
        .to('.hero .title', { opacity: 0, ease: 'power1.in' }, 0)
        .to('.hero .hero-meta, .hero .scroll-cue', { opacity: 0, y: -20, ease: 'none' }, 0);

      // 노트란: 피라미드가 위에서부터 한 층씩 그려진다
      chapterTimeline('.intro')
        .fromTo('.pyramid-tier', { opacity: 0, x: 30 }, { opacity: 1, x: 0, stagger: .07, duration: .16, ease: 'power2.out' }, .14)
        .fromTo('.pyramid-shape path', { strokeDashoffset: 1 }, { strokeDashoffset: 0, stagger: .07, duration: .25, ease: 'power2.out' }, .1);

      // 탑·미들·베이스: 큰 단어가 병 뒤를 가로지른다
      gsap.utils.toArray('.note-chapter').forEach(section => {
        chapterTimeline(section)
          .fromTo(section.querySelectorAll('.giant .line'), { xPercent: i => (i ? 16 : -16) }, { xPercent: i => (i ? -8 : 8), ease: 'none', duration: 1 }, 0)
          .fromTo(section.querySelector('.giant'), { opacity: 0 }, { opacity: 1, duration: .2, ease: 'none' }, 0)
          .to(section.querySelector('.giant'), { opacity: 0, duration: .16, ease: 'none' }, .84)
          .fromTo(section.querySelector('.timeline-fill'), { scaleX: 0 }, { scaleX: 1, duration: .4, ease: 'power2.out' }, .18);
      });

      // 향의 계열: 병을 둘러싼 원이 천천히 돈다
      chapterTimeline('.families')
        .fromTo('.wheel', { rotate: -40, scale: .9 }, { rotate: 20, scale: 1, ease: 'none', duration: 1 }, 0)
        .fromTo('.wheel', { opacity: 0 }, { opacity: 1, duration: .14, ease: 'none' }, .02)
        .fromTo('.wheel-label', { rotate: 40 }, { rotate: -20, ease: 'none', duration: 1 }, 0)
        .to('.wheel', { opacity: 0, duration: .12 }, .86);

      // 향료
      const mat = chapterTimeline('.materials');
      gsap.utils.toArray('.material-row').forEach((row, i) => {
        mat.fromTo(row.querySelector('.material-name'), { xPercent: i % 2 ? -26 : 26 }, { xPercent: i % 2 ? 8 : -8, ease: 'none', duration: 1 }, 0);
      });
      mat.fromTo('.material-rows', { opacity: 0 }, { opacity: 1, duration: .14 }, 0).to('.material-rows', { opacity: 0, duration: .12 }, .86);

      // 농도: 막대가 차오른다
      chapterTimeline('.strengths').fromTo('.strength-bar i', { scaleX: 0 }, { scaleX: 1, stagger: .05, duration: .25, ease: 'power2.out' }, .14);

      // 시향하는 법
      chapterTimeline('.testing');

      // 마지막 장
      gsap.timeline({ scrollTrigger: { trigger: '.begin', start: 'top 70%', end: 'top 5%', scrub: 1.2 } })
        .from('.begin .line-inner', { yPercent: 110, stagger: .1, ease: 'power3.out' })
        .from('.begin .fade-in', { opacity: 0, y: 24, stagger: .1 }, '<.2');
    }, root);
    document.fonts?.ready.then(() => ScrollTrigger.refresh());
    return () => ctx.revert();
  }, [onChapter]);

  return <div className={`entrance${opening ? ' opening' : ''}`} ref={root} inert={opening}>
    <header className="site-head">
      <span className="wordmark">Sillage</span>
      <nav className="head-index" aria-hidden="true"><span>Notes</span><span>Familles</span><span>Matières</span><span>Atelier</span></nav>
      <span className="head-right"><SoundToggle /><span className="head-meta">Maison de parfum — Séoul</span></span>
    </header>
    <div className="grid-lines" aria-hidden="true"><i /><i /><i /><i /><i /></div>

    <section className="hero" data-chapter="hero" aria-labelledby="entrance-title">
      <p className="hero-mark" aria-hidden="true"><Lines lines={['Sillage']} /></p>
      <h1 id="entrance-title" className="title" lang="en" aria-label="The trace a scent leaves — 향이 지나간 자리에 남는 것"><Lines lines={['The trace', <em key="e">a scent leaves</em>]} /><span className="title-ko fade-in">향이 지나간 자리에 남는 것</span></h1>
      <div className="hero-meta">
        <p className="eyebrow fade-in">Sillage <em>[sijaʒ]</em> — 향이 지나간 뒤 공기에 남는 자취</p>
        <p className="lede fade-in">향을 잘 몰라도 괜찮아요. 노트가 무엇인지부터 계열, 재료, 농도, 시향하는 법까지 차례로 알아보고, 마지막에 당신의 향을 함께 찾아요.</p>
      </div>
      <div className="scroll-cue fade-in" aria-hidden="true"><span>Scroll</span><i /></div>
    </section>

    <section className="chapter intro" data-chapter="intro" aria-labelledby="ch-intro">
      <div className="pin">
        <div className="chapter-copy">
          <p className="index reveal"><span>00</span> / 07 — La pyramide</p>
          <h2 id="ch-intro" className="chapter-title" lang="en"><Lines lines={['A sentence', <em key="e">written in time</em>]} /></h2>
          <p className="title-ko reveal">향수는 시간 위에 쓰인 문장이에요</p>
          <p className="body reveal">향수는 한 가지 냄새가 아니에요. 가벼운 향은 빨리 날아가고 무거운 향은 오래 남기 때문에, 시간이 지나며 향이 세 겹으로 바뀌어요. 이 세 겹을 <strong>노트</strong>라고 불러요.</p>
        </div>
        <aside className="chapter-side pyramid" aria-label="노트 피라미드">
          <svg className="pyramid-shape" viewBox="0 0 200 180" aria-hidden="true">
            <path pathLength="1" d="M100 6 L134 62 L66 62 Z" />
            <path pathLength="1" d="M62 70 L138 70 L164 116 L36 116 Z" />
            <path pathLength="1" d="M32 124 L168 124 L194 174 L6 174 Z" />
          </svg>
          <ol>{pyramid.map(tier => <li className="pyramid-tier" key={tier.id}>
            <span className="tier-name">{tier.name}<small>{tier.ko}</small></span>
            <span className="tier-text">{tier.text}</span>
            <span className="tier-time">{tier.time}</span>
          </li>)}</ol>
        </aside>
      </div>
    </section>

    {noteChapters.map(chapter => <section className="chapter note-chapter" key={chapter.id} data-chapter={chapter.id} aria-labelledby={`ch-${chapter.id}`}>
      <div className="pin">
        <p className="giant" aria-hidden="true"><Lines lines={chapter.word} /></p>
        <div className="chapter-copy">
          <p className="index reveal"><span>{chapter.no}</span> / 07 — {chapter.fr}</p>
          <h2 id={`ch-${chapter.id}`} className="chapter-title" lang="en"><Lines lines={[<span key="l">{chapter.en[0]} {chapter.en[1]}</span>]} /></h2>
          <p className="title-ko reveal">{chapter.ko}</p>
          <p className="body reveal">{chapter.body}</p>
        </div>
        <aside className="chapter-side">
          <div className="timeline reveal">
            <span className="label">언제 느껴지나요</span>
            <div className="timeline-track"><i className="timeline-fill" data-stage={chapter.id} /></div>
            <span className="time">{chapter.time}</span>
          </div>
          <ul className="swatches">{chapter.notes.map(id => <li className="reveal" key={id}>
            <NoteIcon id={id} color={byId[id].color} size="sm" />
            <span><strong>{byId[id].name}</strong><small>{byId[id].feel}</small></span>
          </li>)}</ul>
        </aside>
      </div>
    </section>)}

    <section className="chapter families" data-chapter="families" aria-labelledby="ch-families">
      <div className="pin">
        <div className="wheel" aria-hidden="true">
          <i className="wheel-ring" />
          {families.map((family, i) => <span className="wheel-spoke" key={family.en} style={{ '--a': `${i * 360 / families.length - 90}deg`, '--c': family.color }}>
            <span className="wheel-anchor"><span className="wheel-label"><i />{family.ko}<em>{family.en}</em></span></span>
          </span>)}
        </div>
        <div className="chapter-copy">
          <p className="index reveal"><span>04</span> / 07 — Familles</p>
          <h2 id="ch-families" className="chapter-title" lang="en"><Lines lines={['Scent', <em key="e">Families</em>]} /></h2>
          <p className="title-ko reveal">향의 계열</p>
          <p className="body reveal">비슷한 인상의 향끼리 묶은 것을 계열이라고 해요. 좋아하는 계열 하나만 알아도 향수 고르기가 훨씬 쉬워져요. 이웃한 계열끼리는 잘 어울리는 경우가 많아요.</p>
        </div>
        <aside className="chapter-side">
          <ul className="family-list">{families.map(family => <li className="reveal" key={family.en} style={{ '--c': family.color }}>
            <i /><strong>{family.ko}</strong><span>{family.text}</span>
          </li>)}</ul>
        </aside>
      </div>
    </section>

    <section className="chapter materials" data-chapter="materials" aria-labelledby="ch-materials">
      <div className="pin">
        <div className="material-rows" aria-hidden="true">{materials.map(item => <p className="material-name" key={item.fr} style={{ '--c': item.color }}>{item.fr}</p>)}</div>
        <div className="chapter-copy">
          <p className="index reveal"><span>05</span> / 07 — Matières</p>
          <h2 id="ch-materials" className="chapter-title" lang="en"><Lines lines={['Raw', <em key="e">Materials</em>]} /></h2>
          <p className="title-ko reveal">향료, 향의 재료</p>
          <p className="body reveal">같은 노트도 어떤 재료에서 왔는지에 따라 인상이 달라져요. 꽃이나 껍질에서 얻은 천연 원료와, 조향사가 설계한 합성 향료가 함께 쓰여요.</p>
        </div>
        <aside className="chapter-side">
          <ul className="material-list">{materials.map(item => <li className="reveal" key={item.fr}>
            <NoteIcon id={item.icon} color={item.color} size="sm" />
            <span><strong>{item.ko}<em>{item.fr}</em></strong><small>{item.text}</small></span>
          </li>)}</ul>
        </aside>
      </div>
    </section>

    <section className="chapter strengths" data-chapter="strengths" aria-labelledby="ch-strengths">
      <div className="pin">
        <div className="chapter-copy strengths-copy">
          <p className="index reveal"><span>06</span> / 07 — Concentration</p>
          <h2 id="ch-strengths" className="chapter-title" lang="en"><Lines lines={[<span key="l">The <em>Concentration</em></span>]} /></h2>
          <p className="title-ko reveal">향수의 농도</p>
          <p className="body reveal">이름 뒤에 붙는 EDT, EDP는 향료가 얼마나 진하게 들어 있는지를 말해요. 농도가 높을수록 대체로 깊고 오래가지만, 실제 지속력은 향수마다 달라요.</p>
          <ol className="strength-list">{strengths.map(item => <li className="strength-row reveal" key={item.en}>
            <div className="strength-name"><strong>{item.ko}</strong><small>{item.en}</small></div>
            <div className="strength-bar" aria-hidden="true"><i style={{ left: `${item.from / 30 * 100}%`, width: `${(item.to - item.from) / 30 * 100}%` }} /></div>
            <div className="strength-range"><span>{item.range}</span><small>{item.note}</small></div>
          </li>)}</ol>
          <p className="footnote reveal">부향률은 업계에서 흔히 쓰는 대략적인 범위예요. 브랜드마다 기준이 조금씩 달라요.</p>
        </div>
      </div>
    </section>

    <section className="chapter testing" data-chapter="testing" aria-labelledby="ch-testing">
      <div className="pin">
        <div className="chapter-copy">
          <p className="index reveal"><span>07</span> / 07 — Essayer</p>
          <h2 id="ch-testing" className="chapter-title" lang="en"><Lines lines={['The Art of', <em key="e">Testing</em>]} /></h2>
          <p className="title-ko reveal">시향하는 법</p>
          <p className="body reveal">마음에 드는 향을 찾았다면, 실제로 맡아볼 때 이 순서를 기억해 주세요. 향은 시간을 두고 바뀌니까 천천히 만나는 게 좋아요.</p>
        </div>
        <aside className="chapter-side">
          <ol className="steps">{testingSteps.map((step, i) => <li className="reveal" key={step.title}>
            <span className="step-no">{String(i + 1).padStart(2, '0')}</span>
            <span><strong>{step.title}</strong><small>{step.text}</small></span>
          </li>)}</ol>
        </aside>
      </div>
    </section>

    <section className="begin" data-chapter="begin" aria-labelledby="ch-begin">
      <h2 id="ch-begin" className="begin-title" lang="en"><Lines lines={['Now,', <em key="e">find your scent</em>]} /><span className="title-ko fade-in">이제, 당신의 향을 찾아볼 차례예요</span></h2>
      <div className="begin-foot">
        <p className="fade-in">마음에 드는 노트를 여러 개 골라 섞거나, 떠오르는 장면을 말해 주세요.<br />그 조합과 가까운 실제 향수를 찾아드려요.</p>
        <button className="cta fade-in" type="button" onClick={onStart}>
          <span className="cta-fill" aria-hidden="true" />
          <span className="cta-label">Find your scent<small>나의 향수 찾기</small></span>
          <span className="cta-arrow" aria-hidden="true">→</span>
        </button>
      </div>
    </section>
  </div>;
}

/* ───────── 상담 화면 ───────── */

function Scene({ result, pulse, tones, accents, bottle, origin, selection }) {
  const { level } = result;
  const filled = stages.filter(({ id }) => selection[id].length);
  return <section className="scene" id="scent-scene" aria-label="향수병과 향의 색">
    <div className="scene-stage"><Vessel bottle={bottle} tones={tones} accents={accents} level={level || idleLevel} pulse={pulse} origin={origin} /></div>
    <div className="scene-caption">
      <span className="index">Votre parfum</span>
      {filled.length ? <dl className="formula" lang="en">{filled.map(stage => <div key={stage.id}>
        <dt>{stage.en}</dt>
        <dd><span className="formula-en">{selection[stage.id].map(n => byId[n].english).join(', ').replace(/, ([^,]*)$/, ' & $1')}</span>
          <span className="formula-ko" lang="ko">{selection[stage.id].map(n => byId[n].name).join(' · ')}</span></dd>
      </div>)}</dl>
        : <h2 lang="en">Awaiting <em>your notes</em><span className="formula-ko" lang="ko">노트를 고르면 이곳에 당신의 향이 적혀요</span></h2>}
    </div>
  </section>;
}

function BlendPreview({ selection, tones, onRemove }) {
  return <div className="blend-preview" aria-label="나의 블렌드">
    {stages.map((stage, i) => {
      const ids = selection[stage.id];
      const colors = ids.map(n => byId[n].color);
      const bar = colors.length > 1 ? `linear-gradient(90deg, ${colors.join(', ')})` : colors[0] ?? 'transparent';
      return <div className="blend-row" key={stage.id} data-empty={!ids.length}>
        <span className="blend-stage">{stage.en}</span>
        <span className="blend-bar"><i style={{ background: bar }} /></span>
        <span className="blend-result" style={{ '--c': ids.length ? tones[i] : 'transparent' }} title="섞인 색" />
        <span className="blend-chips">{ids.length ? ids.map(n => <button type="button" key={n} onClick={() => onRemove(stage.id, n)}
          style={{ '--c': byId[n].color }} aria-label={`${byId[n].name} 빼기`} title={byId[n].name}><i /><span lang="en">{byId[n].english}</span><b aria-hidden="true">×</b></button>)
          : <em lang="en">Not yet chosen</em>}</span>
      </div>;
    })}
  </div>;
}

// 한 단계의 노트를 4개씩 한 페이지로 묶어 옆으로 넘겨 본다
function NoteRail({ notes, picked, choose, stage, disabled }) {
  const rail = useRef(null);
  const [page, setPage] = useState(0);
  const pages = Math.ceil(notes.length / 4);
  useEffect(() => { rail.current?.scrollTo({ left: 0 }); setPage(0); }, [stage]);
  const go = to => {
    const el = rail.current;
    const next = Math.max(0, Math.min(pages - 1, to));
    el.scrollTo({ left: next * el.clientWidth, behavior: reduceMotion() ? 'instant' : 'smooth' });
  };
  return <div className="note-rail-wrap">
    <div className="note-rail" ref={rail} role="group" aria-label={`${stage} 노트`} data-lenis-prevent
      onScroll={event => setPage(Math.round(event.currentTarget.scrollLeft / event.currentTarget.clientWidth))}>
      {Array.from({ length: pages }, (_, p) => <div className="note-page" key={p}>
        {notes.slice(p * 4, p * 4 + 4).map(note => {
          const on = picked.includes(note.id);
          return <button type="button" className="note" key={note.id} disabled={disabled} aria-pressed={on}
            onClick={() => choose(stage, note.id)} style={{ '--c': note.color }}>
            <NoteIcon id={note.id} color={note.color} />
            <span className="note-text"><strong>{note.name}</strong><small><i lang="en">{note.english}</i>{note.feel}</small></span>
            <span className="check" aria-hidden="true">{on && ['i', 'ii', 'iii'][picked.indexOf(note.id)]}</span>
          </button>;
        })}
      </div>)}
    </div>
    {pages > 1 && <div className="rail-nav">
      <button type="button" onClick={() => go(page - 1)} disabled={page === 0} aria-label="이전 노트">←</button>
      <span className="rail-dots" aria-hidden="true">{Array.from({ length: pages }, (_, p) => <i key={p} data-on={p === page} />)}</span>
      <span className="rail-count">{String(page + 1).padStart(2, '0')} / {String(pages).padStart(2, '0')}</span>
      <button type="button" onClick={() => go(page + 1)} disabled={page === pages - 1} aria-label="다음 노트">→</button>
    </div>}
  </div>;
}

function NotePicker({ selection, choose, disabled, tones, focus }) {
  const [stage, setStage] = useState('top');
  useEffect(() => { if (focus) setStage(focus); }, [focus]);
  const group = stages.find(item => item.id === stage);
  const picked = selection[stage];
  return <section className="picker" aria-labelledby="blend-title">
    <div className="section-label"><span>I.</span><h2 id="blend-title"><b lang="en">Compose your blend</b>노트를 골라 섞기</h2></div>
    <div className="stage-tabs" role="tablist" aria-label="향 노트 단계">
      {stages.map(item => <button key={item.id} role="tab" type="button" aria-selected={stage === item.id} onClick={() => setStage(item.id)}>
        <span className="tab-no">{item.no}</span>
        <span className="tab-name"><b lang="en">{item.en}</b>{item.label}</span>
        <span className="tab-dots">{selection[item.id].length
          ? selection[item.id].map(n => <i key={n} style={{ '--c': byId[n].color }} />)
          : <em>—</em>}</span>
      </button>)}
    </div>
    <p className="stage-hint">{group.detail} <span>· 옆으로 넘겨 보고, 여러 개를 골라 섞을 수 있어요 ({picked.length}/{MAX_PER_STAGE})</span></p>
    <NoteRail notes={notesCatalog.filter(note => note.stage === stage)} picked={picked} choose={choose} stage={stage} disabled={disabled} />
    <BlendPreview selection={selection} tones={tones} onRemove={choose} />
  </section>;
}

function Products({ results, curation, curating, liked, onLike, onShare }) {
  const products = curation?.picks?.length ? curation.picks : results.products;
  const likedIds = new Set(liked.map(item => item.id));
  const ready = curation ? curation.ready : results.ready;
  if (!products.length && !ready && !curating) return null;
  return <section className="products" aria-busy={curating}>
    <div className="section-label"><span>III.</span><h2><b lang="en">{ready ? 'Your selection' : 'First impressions'}</b>{ready ? '최종 시향 추천' : '지금 떠오르는 향수'}</h2></div>
    <div className="curation-head">
      {curation?.ai && <span className="ai-badge">AI 큐레이션</span>}
      {curating && <span className="curating">조합을 읽고 어울리는 향수를 고르는 중<i /><i /><i /></span>}
      {!curating && curation?.summary && <p className="curation-summary">{curation.summary}</p>}
      {!curating && products.length > 0 && <button type="button" className="share-card" onClick={() => onShare(products, curation?.summary)}>
        <span aria-hidden="true">✦</span> 결과 카드 만들기</button>}
    </div>
    {products.length ? <ol className={curating ? 'dim' : ''}>{products.map((item, index) => (
      <li key={item.id} style={{ '--delay': `${120 + index * 100}ms` }}>
        <a className="product" href={item.url} target="_blank" rel="noreferrer">
          <span className="product-no">{String(index + 1).padStart(2, '0')}</span>
          <div><span className="brand">{item.brand}{item.concentration && <em> · {item.concentration}</em>}</span><strong>{item.name}</strong>
            {item.why ? <p className="why">{item.why}</p> : <p>{item.description}</p>}
            <span className="product-notes">{item.notes.join(' · ')}</span>
            {item.matching_notes?.length > 0 && <span className="match">선택한 노트와 겹침 · {item.matching_notes.join(' · ')}</span>}
            <span className="source">노트 출처 보기</span></div>
          <span aria-hidden="true" className="external">↗</span>
        </a>
        <button type="button" className={`like${likedIds.has(item.id) ? ' on' : ''}`} aria-pressed={likedIds.has(item.id)}
          aria-label={likedIds.has(item.id) ? `${item.name} 저장 취소` : `${item.name} 저장`} title={likedIds.has(item.id) ? '저장 취소' : '마음에 들면 저장'}
          onClick={() => onLike(item)}>{likedIds.has(item.id) ? '♥' : '♡'}</button>
      </li>))}</ol> : !curating && <p className="error">고른 노트와 겹치는 향수를 DB에서 찾지 못했어요. 다른 노트를 더해 보세요.</p>}
  </section>;
}

// 저장한 향수(취향 기억). 상담과 추천이 이 목록을 참고한다.
function Shelf({ liked, onRemove, onAsk, disabled }) {
  if (!liked.length) return null;
  return <section className="shelf" aria-labelledby="shelf-title">
    <div className="section-label"><span>IV.</span><h2 id="shelf-title"><b lang="en">My shelf</b>저장한 향수</h2></div>
    <p className="shelf-note">이 브라우저에만 저장돼요. 상담과 AI 큐레이션이 이 취향을 참고해요.</p>
    <ul>{liked.map(item => <li key={item.id}>
      <a href={item.url} target="_blank" rel="noreferrer"><span className="brand">{item.brand}</span><strong>{item.name}</strong></a>
      <button type="button" className="shelf-ask" disabled={disabled} onClick={() => onAsk(item)}>이 향처럼 블렌드</button>
      <button type="button" className="shelf-remove" aria-label={`${item.name} 저장 취소`} onClick={() => onRemove(item)}>×</button>
    </li>)}</ul>
  </section>;
}

// 내 블렌드를 1080×1350 카드 이미지로 그린다(공유·보관용). 서버로 보내지 않고 브라우저 안에서만 만든다.
// 상담 화면 병 속에 지금 보이는 층진 액체를 그대로 옮겨 담고, 아래에 탑·미들·베이스와 시향해 볼 향수를 적는다.
const loadImage = src => new Promise((resolve, reject) => { const im = new Image(); im.onload = () => resolve(im); im.onerror = reject; im.src = src; });
const SANS = '"Pretendard Variable", Pretendard, "Noto Sans KR", sans-serif';
const SERIF = '"Cormorant Garamond", "Times New Roman", serif';

// CSS inset 값(1~4개, %)을 병 상자 안의 사각형으로 바꾼다
function insetBox(inset, x, y, w, h) {
  const v = inset.trim().split(/\s+/).map(n => Number.parseFloat(n) / 100);
  const [t, r, b, l] = v.length === 1 ? [v[0], v[0], v[0], v[0]] : v.length === 2 ? [v[0], v[1], v[0], v[1]]
    : v.length === 3 ? [v[0], v[1], v[2], v[1]] : v;
  return { x: x + w * l, y: y + h * t, w: w * (1 - l - r), h: h * (1 - t - b) };
}

// 병마다 정의한 액체 마스크(clip-path의 polygon 또는 inset round)를 캔버스 경로로 만든다
function maskPath(mask, { x, y, w, h }) {
  const path = new Path2D();
  const poly = mask.match(/^polygon\((.*)\)$/);
  if (poly) {
    poly[1].split(',').forEach((pair, i) => {
      const [px, py] = pair.trim().split(/\s+/).map(n => (n === '0' ? 0 : Number.parseFloat(n) / 100));
      const X = x + w * px, Y = y + h * py;
      if (i) path.lineTo(X, Y); else path.moveTo(X, Y);
    });
    path.closePath();
    return path;
  }
  const round = mask.match(/round\s+([^/]+)\/\s*(.+)\)$/);
  if (round) {
    const [tl, tr, br, bl] = round[1].trim().split(/\s+/).map(n => w * Number.parseFloat(n) / 100);
    const [vtl, vtr, vbr, vbl] = round[2].trim().split(/\s+/).map(n => h * Number.parseFloat(n) / 100);
    path.moveTo(x + tl, y);
    path.lineTo(x + w - tr, y); path.ellipse(x + w - tr, y + vtr, tr, vtr, 0, -Math.PI / 2, 0);
    path.lineTo(x + w, y + h - vbr); path.ellipse(x + w - br, y + h - vbr, br, vbr, 0, 0, Math.PI / 2);
    path.lineTo(x + bl, y + h); path.ellipse(x + bl, y + h - vbl, bl, vbl, 0, Math.PI / 2, Math.PI);
    path.lineTo(x, y + vtl); path.ellipse(x + tl, y + vtl, tl, vtl, 0, Math.PI, Math.PI * 1.5);
    path.closePath();
    return path;
  }
  path.rect(x, y, w, h);
  return path;
}

async function renderShareCard({ selection, tones, products, bottle }) {
  await document.fonts?.ready;
  const W = 1080, H = 1350, c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');
  const ink = '#1c1b18', soft = '#3f3c36', mute = '#66615a', hair = 'rgba(28,27,24,.16)';

  // 바탕: 종이색 위에 세 층의 색이 병 뒤에서 번진다(사이트 배경과 같은 결)
  g.fillStyle = '#efebe4'; g.fillRect(0, 0, W, H);
  [[.5, .26, 620, 'b8'], [.18, .5, 560, '90'], [.84, .56, 560, '90'], [.5, .72, 700, '60']].forEach(([x, y, r, a], i) => {
    const tone = tones[[0, 1, 1, 2][i]];
    const grad = g.createRadialGradient(W * x, H * y, 0, W * x, H * y, r);
    grad.addColorStop(0, tone + a); grad.addColorStop(1, tone + '00');
    g.fillStyle = grad; g.fillRect(0, 0, W, H);
  });
  // 아래쪽 글 영역은 종이색으로 살짝 덮어 읽기 쉽게
  const fade = g.createLinearGradient(0, 760, 0, 940);
  fade.addColorStop(0, 'rgba(239,235,228,0)'); fade.addColorStop(1, 'rgba(239,235,228,.72)');
  g.fillStyle = fade; g.fillRect(0, 760, W, H - 760);

  // 병 + 지금 화면의 층진 액체
  const bh = 700, bw = bh * bottle.ratio, bx = (W - bw) / 2, by = 84;
  const halo = g.createRadialGradient(W / 2, by + bh * .58, 0, W / 2, by + bh * .58, bw * 1.1);
  halo.addColorStop(0, 'rgba(255,255,255,.5)'); halo.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = halo; g.fillRect(0, 0, W, H);
  try {
    const im = await loadImage(`/atelier/${bottle.id}.webp`);
    g.save(); g.shadowColor = tones[2] + '55'; g.shadowBlur = 60; g.shadowOffsetY = 30;
    g.globalAlpha = .92; g.drawImage(im, bx, by, bw, bh); g.restore();
    const liquid = document.querySelector('.scene .liquid-chamber canvas');
    if (liquid?.width) {
      const box = insetBox(bottle.inset, bx, by, bw, bh);
      g.save(); g.clip(maskPath(bottle.mask, box)); g.globalCompositeOperation = 'multiply';
      g.drawImage(liquid, box.x, box.y, box.w, box.h); g.restore();
    }
  } catch { /* 병 이미지를 못 불러와도 카드는 만든다 */ }

  g.textBaseline = 'alphabetic';
  g.fillStyle = ink; g.font = `italic 300 46px ${SERIF}`; g.fillText('Sillage', 72, 104);
  g.textAlign = 'right'; g.fillStyle = mute; g.font = `400 18px ${SANS}`;
  g.fillText(new Date().toLocaleDateString('ko-KR'), W - 72, 100); g.textAlign = 'left';

  // Votre parfum — 탑·미들·베이스
  let y = 818;
  g.strokeStyle = ink; g.lineWidth = 1.5; g.beginPath(); g.moveTo(72, y - 6); g.lineTo(120, y - 6); g.stroke();
  g.fillStyle = mute; g.font = `500 17px ${SANS}`; g.fillText('VOTRE PARFUM', 136, y);
  y += 26;
  stages.filter(s => selection[s.id].length).forEach((stage, i, list) => {
    const ids = selection[stage.id];
    g.strokeStyle = hair; g.lineWidth = 1; g.beginPath(); g.moveTo(72, y); g.lineTo(W - 72, y); g.stroke();
    g.fillStyle = mute; g.font = `500 16px ${SANS}`; g.fillText(stage.en.toUpperCase(), 72, y + 58);
    g.fillStyle = ink; g.font = `italic 400 42px ${SERIF}`;
    g.fillText(ids.map(n => byId[n].english).join(', ').replace(/, ([^,]*)$/, ' & $1'), 196, y + 58, W - 268);
    g.fillStyle = soft; g.font = `400 19px ${SANS}`; g.fillText(ids.map(n => byId[n].name).join(' · '), 198, y + 90, W - 270);
    y += 112;
    if (i === list.length - 1) { g.beginPath(); g.moveTo(72, y); g.lineTo(W - 72, y); g.stroke(); }
  });

  // 시향해 볼 향수
  if (products.length) {
    const top = Math.max(y + 54, 1180);
    g.fillStyle = mute; g.font = `500 16px ${SANS}`; g.fillText('TO TRY  ·  시향해 볼 향수', 72, top);
    products.slice(0, 3).forEach((item, i) => {
      const x = 72 + i * 316;
      g.fillStyle = mute; g.font = `500 14px ${SANS}`; g.fillText(item.brand, x, top + 40, 296);
      g.fillStyle = ink; g.font = `400 28px ${SERIF}`; g.fillText(item.name, x, top + 76, 296);
    });
  }
  return new Promise(resolve => c.toBlob(resolve, 'image/png'));
}

function shareText({ selection, products }) {
  const lines = stages.filter(s => selection[s.id].length)
    .map(s => `${s.label}: ${selection[s.id].map(n => byId[n].name).join(', ')}`);
  const picks = products.slice(0, 3).map(p => `${p.brand} ${p.name}`).join(' / ');
  return `나의 Sillage 블렌드\n${lines.join('\n')}${picks ? `\n시향해 볼 향수: ${picks}` : ''}`;
}

// 결과 카드 창: 카드를 먼저 보여 주고, 공유하기·이미지 저장을 고른다
function ShareDialog({ data, onClose }) {
  const dialog = useRef(null);
  const [card, setCard] = useState(null);
  const [note, setNote] = useState('');
  useEffect(() => {
    const el = dialog.current;
    if (!el.open) el.showModal();
    let url = null, alive = true;
    renderShareCard(data).then(blob => {
      if (!alive || !blob) return;
      url = URL.createObjectURL(blob);
      setCard({ blob, url, file: new File([blob], 'sillage-blend.png', { type: 'image/png' }) });
    });
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [data]);

  function save() {
    if (!card) return;
    const link = document.createElement('a');
    link.href = card.url; link.download = 'sillage-blend.png';
    document.body.append(link); link.click(); link.remove();
    setNote('이미지를 저장했어요.');
  }

  async function share() {
    if (!card) return;
    const text = shareText(data);
    try {
      if (navigator.canShare?.({ files: [card.file] })) {
        await navigator.share({ files: [card.file], title: '나의 Sillage 블렌드', text });
        return;
      }
      if (navigator.share) { await navigator.share({ title: '나의 Sillage 블렌드', text }); return; }
      await navigator.clipboard.writeText(text);
      setNote('이 브라우저는 바로 공유를 지원하지 않아 블렌드 내용을 복사했어요. 이미지는 저장해서 보내 주세요.');
    } catch (error) {
      if (error?.name !== 'AbortError') setNote('공유하지 못했어요. 이미지를 저장해서 보내 주세요.');
    }
  }

  return <dialog className="share-dialog" ref={dialog} onClose={onClose} onCancel={onClose}
    onClick={event => { if (event.target === dialog.current) dialog.current.close(); }} aria-labelledby="share-title">
    <div className="share-panel">
      <button type="button" className="share-close" aria-label="닫기" onClick={() => dialog.current.close()}>×</button>
      <p className="index"><span>Card</span> — 나의 블렌드</p>
      <h2 id="share-title" lang="en">Your <em>blend</em></h2>
      <p className="title-ko">공유하거나 이미지로 간직해 보세요</p>
      <div className="share-preview" aria-busy={!card}>
        {card ? <img src={card.url} alt="나의 블렌드 카드: 고른 노트와 시향해 볼 향수" /> : <span className="share-loading">카드를 만드는 중<i /><i /><i /></span>}
      </div>
      <div className="share-actions">
        <button type="button" className="share-primary" onClick={share} disabled={!card}>공유하기</button>
        <button type="button" className="share-secondary" onClick={save} disabled={!card}>이미지 저장</button>
      </div>
      <p className="share-note" role="status">{note}</p>
    </div>
  </dialog>;
}

// 대화 중 MCP 도구로 확인한 정보(날씨, 향수 조회 등). 실패한 호출과 중복은 숨긴다.
function ToolTrail({ tools }) {
  const seen = new Set();
  const shown = (tools || []).filter(t => t.label !== '확인 실패' && !seen.has(t.label + t.detail) && seen.add(t.label + t.detail)).slice(0, 4);
  if (!shown.length) return null;
  return <ul className="tool-trail" aria-label="확인한 정보">{shown.map((t, i) => <li key={i}>
    <span className="tool-tag" lang="en">MCP</span><b>{t.label}</b>{t.detail && <em>{t.detail}</em>}
  </li>)}</ul>;
}

// 재료 사진 출처 (Wikimedia Commons, 각 라이선스에 따라 배경 제거·자르기)
function ImageCredits() {
  const [credits, setCredits] = useState(null);
  return <details className="credits" onToggle={event => {
    if (event.currentTarget.open && !credits) fetch('/notes/CREDITS.json').then(r => r.json()).then(setCredits).catch(() => setCredits({}));
  }}>
    <summary>재료 사진 출처 · Wikimedia Commons</summary>
    {credits && <ul>{Object.entries(credits).map(([id, item]) => <li key={id}>
      <strong>{byId[id]?.name ?? id}</strong> <a href={item.source} target="_blank" rel="noreferrer">{item.title.replace(/^File:/, '')}</a>
      {item.author && <> · {item.author}</>} · {item.license} · {item.edit}
    </li>)}</ul>}
  </details>;
}

// 사진을 브라우저에서 최대 1024px JPEG로 줄인다(전송량을 줄이고 원본은 어디에도 저장하지 않는다)
function shrinkImage(file) {
  return new Promise((resolve, reject) => {
    if (!file?.type?.startsWith('image/')) { reject(new Error('이미지 파일만 올릴 수 있어요.')); return; }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1024 / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale); canvas.height = Math.round(img.height * scale);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL('image/jpeg', .85));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('사진을 읽지 못했어요.')); };
    img.src = url;
  });
}

function KeyPanel({ status, onChange }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(readKey());
  const label = status?.key === 'user' ? '내 키로 AI 연결' : status?.key === 'server' ? 'AI 연결됨' : '체험 모드';
  function save(event) {
    event.preventDefault();
    try { value.trim() ? sessionStorage.setItem(KEY_STORE, value.trim()) : sessionStorage.removeItem(KEY_STORE); } catch { /* 저장 못 해도 이번 요청엔 무관 */ }
    setOpen(false);
    onChange();
  }
  return <span className="key-panel">
    <button type="button" className={`key-toggle k-${status?.key ?? 'demo'}`} onClick={() => setOpen(v => !v)} aria-expanded={open}>
      <i aria-hidden="true" /><span>{label}</span>
    </button>
    {open && <form className="key-pop" onSubmit={save}>
      <strong>OpenAI API 키</strong>
      <p>내 키를 넣으면 LLM 상담, AI 큐레이션, 사진 분석이 켜져요. 키는 이 탭에만 보관되고, 탭을 닫으면 지워져요. 키가 없으면 데모 모드로 동작해요.</p>
      <input type="password" autoComplete="off" spellCheck={false} placeholder="sk-..." value={value} onChange={event => setValue(event.target.value)} />
      <div className="key-actions">
        {readKey() && <button type="button" onClick={() => { setValue(''); try { sessionStorage.removeItem(KEY_STORE); } catch { /* */ } setOpen(false); onChange(); }}>지우기</button>}
        <button type="submit">저장</button>
      </div>
    </form>}
  </span>;
}

function SoundToggle() {
  const [on, setOn] = useState(sound.enabled);
  useEffect(() => sound.subscribe(setOn), []);
  return <button type="button" className={`sound-toggle${on ? ' on' : ''}`} onClick={() => sound.toggle()}
    aria-pressed={on} aria-label={on ? '효과음 끄기' : '효과음 켜기'} title={on ? '효과음 끄기' : '효과음 켜기'}>
    <span className="bars" aria-hidden="true"><i /><i /><i /><i /></span><span lang="en">Sound</span>
  </button>;
}

/* ───────── 앱 ───────── */

function App() {
  const [view, setView] = useState('entrance');
  const [chapter, setChapter] = useState('hero');
  const [messages, setMessages] = useState([welcome]);
  const [input, setInput] = useState('');
  const [result, setResult] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pulse, setPulse] = useState(0);
  const [flash, setFlash] = useState(0);
  const [bottle] = useState(chooseBottle);
  const [mode, setMode] = useState(null);
  const [selection, setSelection] = useState(noSelection);
  const [curation, setCuration] = useState(null);
  const [curating, setCurating] = useState(false);
  const [focusStage, setFocusStage] = useState(null);
  const [photo, setPhoto] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [intent, setIntent] = useState(null);
  const [shareData, setShareData] = useState(null);
  const [liked, setLiked] = useState(readLiked);
  const [soundHint, setSoundHint] = useState(() => !sound.enabled && !hintSeen());
  const photoInput = useRef(null);
  const controller = useRef(null);
  const blendController = useRef(null);
  const chatResult = useRef(empty);
  const conversation = useRef(null);
  const composer = useRef(null);
  const stage = useRef(null);
  const origin = useRef(null);
  const studioTitle = useRef(null);
  const storyVessel = useRef(null);
  const lenis = useRef(null);
  const backdropOrigin = useRef(null);

  useEffect(() => {
    if (reduceMotion()) return;
    const instance = new Lenis({ lerp: .07, wheelMultiplier: .85, touchMultiplier: 1.2 });
    lenis.current = instance;
    instance.on('scroll', ScrollTrigger.update);
    const tick = time => instance.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    return () => { gsap.ticker.remove(tick); instance.destroy(); };
  }, []);

  const [keyStatus, setKeyStatus] = useState(null);
  const refreshStatus = () => api('/api/status')
    .then(response => response.ok ? response.json() : null)
    .then(status => { if (status) { setMode(status.mode); setKeyStatus(status); } })
    .catch(() => {});
  useEffect(() => { refreshStatus(); }, []);
  useEffect(() => {
    document.documentElement.dataset.dark = view === 'entrance' && scenes[chapter].dark ? '1' : '0';
  }, [view, chapter]);
  useEffect(() => {
    if (conversation.current) conversation.current.scrollTop = conversation.current.scrollHeight;
  }, [messages, busy, error]);
  useEffect(() => {
    backdropOrigin.current = view === 'studio' ? origin.current : storyVessel.current?.querySelector('.vessel');
    if (view === 'studio') {
      studioTitle.current?.focus({ preventScroll: true });
      ScrollTrigger.refresh();
    }
  }, [view]);

  // 노트 조합이 바뀌고 잠시 멈추면 검증된 향수 DB + LLM 큐레이션을 불러온다
  const blendKey = JSON.stringify([compact(selection), intent, liked.map(item => item.id)]);
  useEffect(() => {
    if (view !== 'studio' || !countOf(selection)) { setCuration(null); setCurating(false); return; }
    const request = new AbortController();
    setCurating(true);
    const timer = setTimeout(() => {
      api('/api/recommend', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: request.signal,
        body: JSON.stringify({ blend: compact(selection), intent, liked: liked.map(item => item.id) }),
      }).then(response => response.ok ? response.json() : Promise.reject(response))
        .then(data => { setCuration({ ...data, key: blendKey }); setCurating(false); if (data.ai) sound.arrive(); })
        .catch(() => { if (!request.signal.aborted) setCurating(false); });
    }, 900);
    return () => { clearTimeout(timer); request.abort(); };
  }, [blendKey, view]);

  // 입장 전환: 병 모서리의 빛이 번지고(배경 플래시 + Lottie), 같은 병이 상담 화면의 자리로 날아간다
  useLayoutEffect(() => {
    if (view !== 'opening') return;
    const vessel = storyVessel.current;
    const from = vessel.getBoundingClientRect();
    const to = origin.current.getBoundingClientRect();
    const dx = to.left - from.left, dy = to.top - from.top, s = to.height / from.height;
    const flight = vessel.animate([
      { transform: 'translate(0,0) scale(1)', offset: 0 },
      { transform: 'translate(0,-1.5%) scale(1.03)', offset: .22 },
      { transform: `translate(${dx}px, ${dy}px) scale(${s})`, offset: 1 },
    ], { duration: 1600, easing: 'cubic-bezier(.65,0,.2,1)', fill: 'forwards' });
    flight.onfinish = () => {
      lenis.current?.scrollTo(0, { immediate: true, force: true });
      window.scrollTo(0, 0);
      setView('studio');
    };
    return () => flight.cancel();
  }, [view]);

  function start() {
    sound.enter();
    setFlash(value => value + 1);
    setView(reduceMotion() ? 'studio' : 'opening');
  }

  function present(data) {
    setResult(data);
    setPulse(value => value + 1);
  }

  async function choose(stageId, id) {
    if (controller.current) return;
    blendController.current?.abort();
    const current = selection[stageId];
    const ids = current.includes(id) ? current.filter(n => n !== id) : [...current, id].slice(-MAX_PER_STAGE);
    if (current.includes(id)) sound.deselect(); else sound.select(stages.findIndex(st => st.id === stageId));
    const next = { ...selection, [stageId]: ids };
    setSelection(next);
    setError('');
    if (!countOf(next)) {
      blendController.current = null;
      present(chatResult.current);
      return;
    }
    const request = new AbortController();
    blendController.current = request;
    try {
      const response = await api('/api/blend', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: request.signal,
        body: JSON.stringify({ blend: compact(next) }),
      });
      if (!response.ok) throw new Error('blend request failed');
      const data = await response.json();
      if (blendController.current === request) present(data);
    } catch {
      if (!request.signal.aborted) setError('노트 조합을 불러오지 못했어요. 다시 골라 주세요.');
    } finally {
      if (blendController.current === request) blendController.current = null;
    }
  }

  async function attach(file) {
    try { setPhoto(await shrinkImage(file)); setError(''); }
    catch (failure) { setError(failure.message); }
  }

  async function send(text) {
    const image = photo;
    const content = text.trim() || (image ? '이 사진의 분위기로 향을 찾아줘' : '');
    if (!content || controller.current) return;
    blendController.current?.abort();
    const next = [...messages, { role: 'user', content, image }];
    const request = new AbortController();
    controller.current = request;
    setInput('');
    setPhoto(null);
    setError('');
    setBusy(true);
    setMessages(next);
    try {
      const response = await api('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: request.signal,
        body: JSON.stringify({ messages: next.slice(-15).map(({ role, content }) => ({ role, content })), blend: compact(selection), image,
          liked: liked.map(item => item.id) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '입력 내용을 확인해 주세요.');
      if (controller.current !== request) return;
      const blend = normalize(data.blend);
      setSelection(blend);
      chatResult.current = countOf(blend) ? empty : data;
      present(data);
      setMode(data.demo ? 'demo' : 'llm');
      if (data.intent) setIntent(data.intent);
      setMessages([...next, { role: 'assistant', content: data.reply, changes: data.changes ?? [], tools: data.tools ?? [] }]);
      if (data.changes?.length) { setFocusStage(data.changes[data.changes.length - 1].stage); sound.pour(); }
      if (matchMedia('(max-width: 900px)').matches && stage.current.getBoundingClientRect().top < -100) {
        stage.current.scrollIntoView({ behavior: reduceMotion() ? 'instant' : 'smooth' });
      }
    } catch (failure) {
      if (request.signal.aborted) return;
      setMessages(messages);
      setInput(text);
      setPhoto(image);
      setError(failure instanceof SyntaxError || failure instanceof TypeError
        ? '연결이 잠시 끊겼어요. 다시 보내 주세요.' : failure.message);
    } finally {
      if (controller.current === request) {
        controller.current = null;
        setBusy(false);
        composer.current?.focus({ preventScroll: true });
      }
    }
  }

  function toggleLike(item) {
    setLiked(list => {
      const next = list.some(x => x.id === item.id) ? list.filter(x => x.id !== item.id)
        : [...list, { id: item.id, brand: item.brand, name: item.name, url: item.url }].slice(-20);
      writeLiked(next);
      return next;
    });
  }

  function dismissHint() {
    setSoundHint(false);
    try { localStorage.setItem(HINT_STORE, '1'); } catch { /* 다시 보여도 무방 */ }
  }

  function reset() {
    controller.current?.abort();
    blendController.current?.abort();
    controller.current = null;
    blendController.current = null;
    chatResult.current = empty;
    setSelection(noSelection);
    setMessages([welcome]); setResult(empty); setInput(''); setError(''); setBusy(false); setPulse(value => value + 1); setIntent(null);
    composer.current?.focus({ preventScroll: true });
  }

  const defaults = liquidColors(result.palette);
  // 단계마다 고른 노트들의 색을 OKLab에서 섞어 그 층의 색으로 쓴다
  const tones = stages.map(({ id }, index) => blendColors(selection[id].map(n => byId[n].color)) ?? defaults[index]);
  const accents = stages.map(({ id }) => selection[id].map(n => byId[n].color));
  const backdropTarget = view === 'entrance'
    ? { ...scenes[chapter], flow: storyFlow }
    : { tones, dark: 0, reach: result.level > 0 || countOf(selection) ? 1.25 : .7 };

  return <>
    <Backdrop target={backdropTarget} ripple={view === 'studio' ? pulse : 0} flash={flash} originRef={backdropOrigin} />
    <div className="grain" aria-hidden="true" />
    {view !== 'studio' && <>
      <Entrance opening={view === 'opening'} onChapter={setChapter} onStart={start} />
      <StoryVessel bottle={bottle} chapter={chapter} opening={view === 'opening'} vesselRef={storyVessel} />
    </>}
    {view !== 'entrance' && <main className={`studio-layout${view === 'opening' ? ' entering' : ''}`} inert={view === 'opening'}>
      <header className="site-head studio-head">
        <a className="wordmark" href="/" aria-label="Sillage 처음으로">Sillage</a>
        <span className="head-meta">L’atelier — 향의 아틀리에</span>
        <span className="head-right"><KeyPanel status={keyStatus} onChange={refreshStatus} /><SoundToggle /><button className="ghost" type="button" onClick={reset}><span aria-hidden="true">↺</span><span className="ghost-label"> 새로 시작</span></button></span>
      </header>
      {soundHint && view === 'studio' && <div className="sound-hint" role="status">
        <span>효과음을 켜면 노트를 고를 때 유리잔 소리가 나요</span>
        <button type="button" onClick={() => { if (!sound.enabled) sound.toggle(); dismissHint(); }}>켜기</button>
        <button type="button" aria-label="안내 닫기" onClick={dismissHint}>×</button>
      </div>}
      {shareData && <ShareDialog data={shareData} onClose={() => setShareData(null)} />}
      <div className="studio" ref={stage}>
        <Scene result={result} pulse={pulse} tones={tones} accents={accents} bottle={bottle} origin={origin} selection={selection} />
        <section className="consult" aria-labelledby="page-title">
          <div className="consult-intro">
            <p className="index"><span>Atelier</span> — 나만의 블렌드</p>
            <h1 id="page-title" tabIndex={-1} ref={studioTitle} lang="en">The <em>Atelier</em></h1>
            <p className="title-ko">향의 아틀리에</p>
            <p className="lede">단계마다 마음에 드는 노트를 여러 개 골라 섞어 보세요. 고른 색이 병 속에서 층을 이루며 섞이고, 그 조합과 가까운 향수를 찾아드려요.</p>
          </div>
          <NotePicker selection={selection} choose={choose} disabled={busy} tones={tones} focus={focusStage} />
          <section className="talk" aria-labelledby="talk-title">
            <div className="section-label"><span>II.</span><h2 id="talk-title"><b lang="en">Or, in your words</b>또는, 말로 들려주세요</h2></div>
            <div className="conversation" ref={conversation} role="log" aria-label="향수 상담 대화">
              {messages.map((message, i) => <div className={`message ${message.role}`} key={i}>{message.image && <img className="message-photo" src={message.image} alt="보낸 사진" />}<p>{message.content}</p>
                {message.changes?.length > 0 && <ul className="changes" aria-label="바뀐 노트">{message.changes.map(change => <li key={change.stage}>
                  <span className="change-stage" lang="en">{change.stage}</span>
                  {change.removed.map(name => <s key={name}>{name}</s>)}
                  {change.added.map(name => <b key={name}>{name}</b>)}
                </li>)}</ul>}
                {message.tools?.length > 0 && <ToolTrail tools={message.tools} />}
              </div>)}
              {busy && <div className="message assistant"><p className="working">향을 떠올리는 중<span>…</span></p></div>}
              {error && <p className="error">{error}</p>}
            </div>
            {messages.length === 1 && <div className="examples" aria-label="예시 문장">
              {examples.map(example => <button type="button" key={example} onClick={() => send(example)}>{example}</button>)}
            </div>}
            {photo && <div className="photo-pending"><img src={photo} alt="보낼 사진" /><span>이 사진의 분위기로 향을 찾아요<small>사진은 저장하지 않고 분석에만 써요</small></span>
              <button type="button" onClick={() => setPhoto(null)} aria-label="사진 빼기">×</button></div>}
            <form onSubmit={event => { event.preventDefault(); send(input); }} className={`composer${dragging ? ' dragging' : ''}`}
              onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
              onDrop={event => { event.preventDefault(); setDragging(false); attach(event.dataTransfer.files[0]); }}
              onPaste={event => { const file = [...event.clipboardData.files].find(f => f.type.startsWith('image/')); if (file) attach(file); }}>
              <button type="button" className="photo-button" onClick={() => photoInput.current?.click()} aria-label="사진으로 향 찾기" title="사진으로 향 찾기">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="13" rx="3" /><path d="M8.5 6l1.4-2h4.2l1.4 2" /><circle cx="12" cy="12.5" r="3.4" /></svg>
              </button>
              <input ref={photoInput} type="file" accept="image/*" hidden onChange={event => { attach(event.target.files[0]); event.target.value = ''; }} />
              <div className="composer-field"><TextInput ref={composer} label="찾고 있는 향" isLabelHidden
                placeholder="장면을 말하거나, 사진을 올려 보세요" value={input} onChange={value => setInput(value.slice(0, 1000))} /></div>
              <Button label="보내기" type="submit" variant="primary" size="md" isIconOnly
                icon={<span aria-hidden="true">↑</span>} isDisabled={!input.trim() && !photo} isLoading={busy} />
            </form>
            {mode === 'demo' && <p className="mode-note">체험 모드예요. 날씨와 향수 조회는 그대로 되고, 오른쪽 위 <b>체험 모드</b>를 눌러 OpenAI 키를 넣으면 AI 상담과 AI 큐레이션이 켜져요.</p>}
            {mode === 'incomplete' && <p className="mode-note">LLM 연결 설정을 완료하면 상담을 시작할 수 있어요.</p>}
          </section>
          <Products results={result} curation={curation?.key === blendKey ? curation : null} curating={curating}
            liked={liked} onLike={toggleLike} onShare={(products, summary) => setShareData({ selection, tones, products, summary, bottle })} />
          <Shelf liked={liked} disabled={busy} onRemove={toggleLike} onAsk={item => send(`${item.name} 같은 향으로 만들어 줘`)} />
          <ImageCredits />
        </section>
      </div>
    </main>}
  </>;
}

createRoot(document.getElementById('root')).render(<Theme theme={neutralTheme} mode="light"><App /></Theme>);
