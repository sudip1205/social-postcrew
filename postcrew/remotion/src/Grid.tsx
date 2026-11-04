import React from "react";
import {interpolate} from "remotion";
import {FONT, MONO, useT, useTheme} from "./theme";
import type {GridStep, GridViz, Scene} from "./types";

// one colour per plus, in the order the step lists them (blue, orange, green, pink): a plus keeps its colour from step to step
const PLUS = ["#279CF5", "#F59E0B", "#22C55E", "#EC4899"];

/** A real 2-D board: rows and columns as they are, cells lit, ruled out or marked as the voice speaks, and plus shapes drawn whole. */
export const Grid: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const th = useTheme(), {t} = useT();
  const g = s.grid as GridViz;
  const rows = g.rows, nr = rows.length, nc = rows[0]?.length ?? 1;
  const steps = g.steps ?? [];
  const k = steps.reduce((acc, st, i) => (st.t <= t ? i : acc), -1);
  const cur: GridStep | undefined = k >= 0 ? steps[k] : undefined;
  const since = cur ? t - cur.t : 0;
  // the board fills the width (Short: 888 px inside the margins; long video: the left 60%)
  const boardW = short ? 888 : 1000, boardH = short ? 980 : 760;
  const cell = Math.floor(Math.min(boardW / nc, boardH / nr, short ? 150 : 120));
  const gap = Math.max(4, Math.round(cell * 0.06));
  const appear = interpolate(t, [0, 0.5], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const blocked = new Set(g.blocked ?? []);
  const key = (r: number, c: number) => `${r},${c}`;
  const has = (xs: number[][] | undefined, r: number, c: number) => !!xs?.some(([a, b]) => a === r && b === c);
  const plusAt = new Map<string, number>();
  (cur?.pluses ?? []).forEach((p, i) => p.cells.forEach(([r, c]) => { if (!plusAt.has(key(r, c))) plusAt.set(key(r, c), i); }));
  const overlap = new Set<string>();
  (cur?.pluses ?? []).forEach((p, i) => p.cells.forEach(([r, c]) => { const j = plusAt.get(key(r, c)); if (j !== undefined && j !== i) overlap.add(key(r, c)); }));
  const grow = interpolate(since, [0, 0.45], [0.55, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});

  const board = (
    <div style={{display: "grid", gridTemplateColumns: `repeat(${nc}, ${cell}px)`, gap, padding: gap, borderRadius: 18,
      background: th.surface, border: `2px solid ${th.rule}`, opacity: appear}}>
      {rows.flatMap((row, r) => row.split("").map((ch, c) => {
        const isBlocked = blocked.has(ch);
        const pi = plusAt.get(key(r, c));
        const clash = overlap.has(key(r, c));
        const found = has(cur?.found, r, c), active = has(cur?.active, r, c), out = has(cur?.out, r, c);
        const mark = cur?.marks.find((m) => m.at[0] === r && m.at[1] === c);
        const own = g.colors?.[ch];   // the cell's own colour when the problem names one ("G=green")
        const fill = clash ? "#EF4444" : pi !== undefined ? PLUS[pi % PLUS.length] : found ? th.positive : active ? th.accentSoft : own ? `${own}55` : isBlocked ? `${th.muted}33` : "transparent";
        const border = clash ? "#EF4444" : pi !== undefined ? PLUS[pi % PLUS.length] : found ? th.positive : active ? th.accent : own ? own : th.rule;
        const lit = pi !== undefined || clash || found;
        return (
          <div key={key(r, c)} style={{width: cell, height: cell, borderRadius: Math.round(cell * 0.14), position: "relative",
            background: fill, border: `${active || lit ? 4 : 2}px solid ${border}`, opacity: out ? 0.3 : 1,
            transform: lit ? `scale(${grow})` : undefined, display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: MONO, fontWeight: 700, fontSize: Math.round(cell * 0.38), color: lit ? "#fff" : isBlocked ? th.muted : th.text}}>
            {isBlocked && !lit && !own ? <span style={{fontSize: Math.round(cell * 0.5), opacity: 0.8}}>×</span> : ch}
            {mark && <div style={{position: "absolute", top: -Math.round(cell * 0.42), left: "50%", transform: "translateX(-50%)", whiteSpace: "nowrap",
              fontFamily: FONT, fontSize: Math.max(22, Math.round(cell * 0.24)), fontWeight: 700, color: th.accent}}>▼ {mark.name}</div>}
          </div>
        );
      }))}
    </div>
  );
  // the row and column numbers, so "row 2, column 3" and "above" and "below" can be seen
  const axis = (n: number, vertical: boolean) => (
    <div style={{display: "flex", flexDirection: vertical ? "column" : "row", gap, padding: vertical ? `${gap}px 0` : `0 ${gap}px`}}>
      {Array.from({length: n}, (_, i) => <div key={i} style={{width: vertical ? 34 : cell, height: vertical ? cell : 34, display: "flex",
        alignItems: "center", justifyContent: "center", fontFamily: MONO, fontSize: 22, color: th.muted}}>{i}</div>)}
    </div>
  );
  return (
    <div style={{flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: short ? 34 : 22, paddingTop: short ? 20 : 0}}>
      {g.title && <div style={{fontFamily: FONT, fontSize: short ? 58 : 46, fontWeight: 700, letterSpacing: -1, color: th.text, textAlign: "center"}}>{g.title}</div>}
      <div style={{display: "flex", flexDirection: "column", alignItems: "flex-start"}}>
        <div style={{marginLeft: 34}}>{axis(nc, false)}</div>
        <div style={{display: "flex"}}>{axis(nr, true)}{board}</div>
      </div>
      {(cur?.pluses ?? []).length > 0 && (
        <div style={{display: "flex", gap: 26, flexWrap: "wrap", justifyContent: "center"}}>
          {cur!.pluses.map((p, i) => <span key={i} style={{display: "inline-flex", alignItems: "center", gap: 12, fontFamily: MONO, fontSize: short ? 34 : 28,
            fontWeight: 700, color: th.text}}><span style={{width: 26, height: 26, borderRadius: 6, background: PLUS[i % PLUS.length]}} />{p.label}</span>)}
          {overlap.size > 0 && <span style={{fontFamily: MONO, fontSize: short ? 34 : 28, fontWeight: 700, color: "#EF4444"}}>overlap</span>}
        </div>
      )}
      {cur?.note && <div style={{fontFamily: FONT, fontSize: short ? 54 : 40, fontWeight: 600, letterSpacing: -0.8, color: th.text, textAlign: "center",
        opacity: interpolate(since, [0, 0.3], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}}>{cur.note}</div>}
      {g.legend.length > 0 && <div style={{display: "flex", gap: 30, fontFamily: MONO, fontSize: short ? 28 : 24, color: th.muted}}>{g.legend.map((l) => <span key={l}>{l}</span>)}</div>}
    </div>
  );
};
