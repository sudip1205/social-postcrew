import React from "react";
import {FONT, MONO, ease, useT, useTheme} from "./theme";
import type {PathsViz, Scene} from "./types";

/*
 * A real staircase and every way up it. A little figure hops from step to step along an arrow, one way after another, while the counter climbs and each
 * way is written down. Python (postcrew/pathviz.py) finds the ways and times them; this only draws a frame.
 */
const ORANGE = "#FFB020";
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const W = 840, H = 540, GROUND = 64, HEAD = 130;

type Pt = {x: number; y: number};
const bez = (a: Pt, c: Pt, b: Pt, s: number): Pt => ({x: (1 - s) * (1 - s) * a.x + 2 * (1 - s) * s * c.x + s * s * b.x, y: (1 - s) * (1 - s) * a.y + 2 * (1 - s) * s * c.y + s * s * b.y});

export const StairsCard: React.FC<{viz: PathsViz}> = ({viz}) => {
  const th = useTheme(), {t} = useT();
  const n = viz.n, dx = W / (n + 1), dy = (H - GROUND - HEAD) / n, per = viz.per;
  const top = (i: number) => H - GROUND - i * dy;
  const at = (i: number): Pt => ({x: i * dx + dx / 2, y: top(i) - 26});
  const hopColor = (h: number) => (h === 1 ? th.accent : h === 2 ? ORANGE : th.positive);

  let k = -1;
  viz.paths.forEach((p, i) => { if (t >= p.t) k = i; });
  const cur = k >= 0 ? viz.paths[k] : null, e = cur ? t - cur.t : 0;
  const hops = cur?.hops ?? [], hopDur = hops.length ? (per * 0.8) / hops.length : 1;
  const levels = hops.reduce<number[]>((acc, h) => [...acc, acc[acc.length - 1] + h], [0]);
  const found = viz.paths.filter((p) => t >= p.t + per * 0.85);
  const all = found.length === viz.paths.length;

  let kid = at(0);
  if (cur) {
    const j = Math.min(hops.length - 1, Math.max(0, Math.floor(e / hopDur)));
    const a = at(levels[j]), b = at(levels[j + 1]), c = {x: (a.x + b.x) / 2, y: Math.min(a.y, b.y) - 62 - 12 * hops[j]};
    const s = clamp01(e / hopDur - j);
    kid = e >= hops.length * hopDur ? at(n) : bez(a, c, b, ease(s));
  }
  return (
    <div>
      <div style={{display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: 26, color: th.muted, letterSpacing: 2}}>
        <span>{n} {n === 1 ? "STEP" : "STEPS"}</span>
        <span>WAYS <span style={{fontFamily: MONO, fontSize: 40, color: all ? th.positive : th.accent}}>{found.length}</span></span>
      </div>
      <svg width={W} height={H} style={{display: "block", margin: "6px auto 0"}}>
        {Array.from({length: n + 1}).map((_, i) => (
          <g key={i}>
            <rect x={i * dx + 2} y={top(i)} width={dx - 4} height={H - top(i)} rx={6} fill={th.accentSoft} stroke={th.rule} strokeWidth={2} />
            <text x={i * dx + dx / 2} y={top(i) + 40} textAnchor="middle" fontFamily={MONO} fontWeight={700} fontSize={i === 0 ? 22 : 30} fill={th.muted}>{i === 0 ? "start" : i}</text>
          </g>
        ))}
        <text x={at(n).x} y={at(n).y - 38} textAnchor="middle" fontSize={34}>🏁</text>
        {cur && hops.map((h, j) => {
          const a = at(levels[j]), b = at(levels[j + 1]), c = {x: (a.x + b.x) / 2, y: Math.min(a.y, b.y) - 62 - 12 * h};
          const p = clamp01((e - j * hopDur) / hopDur);
          return p > 0 ? (
            <path key={j} d={`M ${a.x} ${a.y} Q ${c.x} ${c.y} ${b.x} ${b.y}`} pathLength={1} fill="none" stroke={hopColor(h)} strokeWidth={7} strokeLinecap="round"
              strokeDasharray="1" strokeDashoffset={1 - p} style={{filter: `drop-shadow(0 0 8px ${hopColor(h)})`}} />
          ) : null;
        })}
        {cur && hops.map((h, j) => {
          const b = at(levels[j + 1]), c = {x: (at(levels[j]).x + b.x) / 2, y: Math.min(at(levels[j]).y, b.y) - 62 - 12 * h};
          const p = clamp01((e - j * hopDur) / hopDur);
          return p >= 1 ? <text key={j} x={c.x} y={bez(at(levels[j]), c, b, 0.5).y - 12} textAnchor="middle" fontFamily={MONO} fontWeight={700} fontSize={26} fill={hopColor(h)}>+{h}</text> : null;
        })}
        <g transform={`translate(${kid.x} ${kid.y})`}>
          <circle r={20} fill={th.text} stroke={th.accent} strokeWidth={4} />
          <circle cx={-6} cy={-4} r={3} fill={th.bg} /><circle cx={6} cy={-4} r={3} fill={th.bg} />
          <path d="M -7 5 Q 0 12 7 5" stroke={th.bg} strokeWidth={3} fill="none" strokeLinecap="round" />
        </g>
      </svg>
      <div style={{display: "flex", flexWrap: "wrap", alignItems: "flex-start", alignContent: "flex-start", gap: 10, marginTop: 14, minHeight: 110}}>
        {viz.paths.map((p, i) => {
          const a = ease(clamp01((t - (p.t + per * 0.85)) / 0.3));
          return a > 0 ? (
            <span key={i} style={{fontFamily: MONO, fontWeight: 700, fontSize: n > 4 ? 25 : 30, color: th.text, padding: "4px 14px", borderRadius: 12, border: `2px solid ${th.accent}`,
              background: th.accentSoft, opacity: a, transform: `scale(${0.8 + 0.2 * a})`}}>{p.label}</span>
          ) : null;
        })}
      </div>
    </div>
  );
};

export const Stairs: React.FC<{s: Scene; short: boolean}> = ({s}) => {
  const th = useTheme();
  const viz = s.paths;
  return (
    <div style={{flex: 1, display: "flex", flexDirection: "column", gap: 26, minHeight: 0}}>
      <div style={{fontWeight: 700, fontSize: 50, lineHeight: 1.1, letterSpacing: -1, color: th.text}}>{s.title}</div>
      {viz && (
        <div style={{flex: 1, border: `2px solid ${th.rule}`, borderRadius: 22, background: th.surface, padding: "18px 24px 20px", boxShadow: `0 0 40px ${th.accentSoft}`, overflow: "hidden", fontFamily: FONT, display: "flex", flexDirection: "column"}}>
          <div style={{fontWeight: 600, fontSize: 25, color: th.muted, marginBottom: 12, letterSpacing: 1}}>{viz.title}</div>
          <div style={{flex: 1, display: "flex", flexDirection: "column", justifyContent: "center"}}><StairsCard viz={viz} /></div>
        </div>
      )}
    </div>
  );
};
