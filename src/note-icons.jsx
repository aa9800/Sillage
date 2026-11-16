import React from 'react';
import notesCatalog from '../blend-notes.json';

// 노트 표식. 실사 이미지(배경 없는 webp)가 있으면 색 오라 위에 재료 사진을 띄우고,
// 없으면 오라 위에 영문 이니셜을 세리프 이탤릭으로 얹는다.
const byId = Object.fromEntries(notesCatalog.map(note => [note.id, note]));

export function NoteIcon({ id, color, size = 'md', letter }) {
  const note = byId[id];
  const image = note?.image;
  return <span className={`aura aura-${size}${image ? ' has-image' : ''}`} style={{ '--c': color }} aria-hidden="true">
    <span className="aura-swirl" />
    {image
      ? <img src={`/notes/${id}.webp`} alt="" loading="lazy" decoding="async" />
      : <em>{letter ?? note?.english[0] ?? ''}</em>}
  </span>;
}
