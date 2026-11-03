import React from "react";
import {FONT, MONO, ease, useT, useTheme} from "./theme";
import {Colored, EXT} from "./code";
import type {Scene, Viz, VizCell, VizEvent} from "./types";

/*
 * Code plus a picture of it running. The editor window shows the real code and lights the line that is running; under it a picture follows the same
 * steps: a recursion tree growing call by call (repeated work glows, a memo answers at once) or a table filling cell by cell. Python
 * (postcrew/codeviz.py) runs the recursion and times the steps; this only draws a frame.
 */
const WARN = "#FFB020";
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

const Pop: React.FC<{at: number; t: number; children: React.ReactNode; style?: React.CSSProperties}> = ({at, t, children, style}) => {
  const p = ease(clamp01((t - at) / 0.35));
  return <div style={{opacity: p, transform: `scale(${0.7 + 0.3 * p})`, ...style}}>{children}</div>;
};

/** The line running now: the line of the last step that has started. */
const activeLine = (viz: Viz | undefined, t: number): number => {
  const steps: {t: number; line: number}[] = viz?.kind === "calls" ? (viz.events ?? []) : (viz?.cells ?? []);
  let line = 0;
  for (const e of steps) if (e.t <= t && e.line > 0) line = e.line;
  return line;
};

const Editor: React.FC<{s: Scene; t: number; active: number}> = ({s, t, active}) => {
  const th = useTheme();
  const lines = s.code.replace(/\s+$/, "").split("\n");
  const size = Math.min(34, (780 / Math.max(14, ...lines.map((l) => l.length))) * 1.7);
  const file = `main.${EXT[(s.language || "").toLowerCase()] ?? "txt"}`;
  return (
    <div style={{border: `2px solid ${th.rule}`, borderRadius: 22, overflow: "hidden", background: th.surface, boxShadow: `0 0 40px ${th.accentSoft}`, flexShrink: 0}}>
      <div style={{height: 46, display: "flex", alignItems: "center", gap: 9, padding: "0 20px", background: th.accentSoft, borderBottom: `2px solid ${th.rule}`}}>
        {[0, 1, 2].map((i) => <span key={i} style={{width: 12, height: 12, borderRadius: 12, background: th.muted, opacity: 0.6}} />)}
        <span style={{marginLeft: 14, fontFamily: MONO, fontSize: 19, color: th.muted}}>{file}</span>
        <span style={{marginLeft: "auto", fontFamily: MONO, fontSize: 16, color: th.muted, letterSpacing: 2, textTransform: "uppercase"}}>{s.language}</span>
      </div>
      <div style={{padding: "16px 20px", fontFamily: MONO, fontSize: size, lineHeight: 1.5, fontVariantLigatures: "none"}}>
        {lines.map((l, i) => {
          const on = active === i + 1, a = ease(clamp01((t - 0.1 - i * 0.07) / 0.3));
          return (
            <div key={i} style={{display: "flex", gap: 20, whiteSpace: "pre", opacity: (on ? 1 : active ? 0.55 : 1) * a, background: on ? th.accentSoft : "transparent", margin: "0 -20px", padding: "0 20px",
              borderLeft: `5px solid ${on ? th.accent : "transparent"}`, boxShadow: on ? `0 0 22px ${th.accentSoft}` : "none"}}>
              <span style={{color: on ? th.accent : th.muted, minWidth: 30, textAlign: "right"}}>{i + 1}</span>
              <span><Colored line={l} /></span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Counter: React.FC<{items: {k: string; v: number | string; color: string}[]}> = ({items}) => {
  const th = useTheme();
  return (
    <div style={{display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: 26, color: th.muted, letterSpacing: 2}}>
      {items.map((it, i) => <span key={i}>{it.k} <span style={{fontFamily: MONO, fontSize: 36, color: it.color}}>{it.v}</span></span>)}
    </div>
  );
};

const Tree: React.FC<{viz: Viz; t: number}> = ({viz, t}) => {
  const th = useTheme();
  const nodes = viz.nodes ?? [], events = viz.events ?? [];
  const W = 840, H = 440, leaves = viz.leaves ?? 1, levels = viz.levels ?? 1;
  const nw = Math.max(58, Math.min(150, W / leaves - 6)), nh = Math.max(46, Math.min(72, H / levels - 18));
  const fs = Math.max(17, Math.min(30, nw * 0.27));
  const appeared = (i: number) => events.find((e) => e.node === i && e.kind === "call")?.t ?? 1e9;
  const done = (i: number) => events.find((e) => e.node === i && e.kind !== "call")?.t ?? 1e9;
  const last = [...events].reverse().find((e) => e.t <= t);
  const seen = nodes.filter((_, i) => appeared(i) <= t), calls = seen.length;
  const dups = seen.filter((n) => n.dup && !n.hit).length, hits = seen.filter((n, i) => n.hit && done(nodes.indexOf(n)) <= t).length;
  const px = (n: {x: number}) => nw / 2 + n.x * (W - nw), py = (n: {y: number}) => nh / 2 + n.y * (H - nh);
  return (
    <div>
      <Counter items={[{k: "CALLS", v: calls, color: th.accent}, viz.memo ? {k: "MEMO HITS", v: hits, color: th.positive} : {k: "REPEATED", v: dups, color: dups ? WARN : th.muted}]} />
      <div style={{position: "relative", width: W, height: H, margin: "14px auto 0"}}>
        <svg width={W} height={H} style={{position: "absolute", inset: 0}}>
          {nodes.map((n, i) => n.parent >= 0 && (
            <line key={i} x1={px(nodes[n.parent])} y1={py(nodes[n.parent]) + nh / 2} x2={px(n)} y2={py(n) - nh / 2} stroke={n.dup && !viz.memo ? WARN : th.accent}
              strokeWidth={3} opacity={0.7 * ease(clamp01((t - appeared(i)) / 0.3))} />
          ))}
        </svg>
        {nodes.map((n, i) => {
          const ap = appeared(i), fin = done(i) <= t, isLast = last?.node === i;
          const col = n.hit ? th.positive : n.dup && !viz.memo ? WARN : fin ? th.positive : th.accent;
          return (
            <Pop key={i} at={ap} t={t} style={{position: "absolute", left: px(n) - nw / 2, top: py(n) - nh / 2, width: nw, height: nh, borderRadius: 14, border: `3px solid ${col}`,
              background: fin ? "rgba(61,220,151,0.12)" : th.accentSoft, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", fontFamily: MONO, fontWeight: 700,
              boxShadow: isLast ? `0 0 26px ${col}` : n.dup && !viz.memo ? `0 0 14px ${WARN}66` : "none"}}>
              <span style={{fontSize: fs, color: th.text, lineHeight: 1.1}}>{n.label}</span>
              {fin && <span style={{fontSize: fs * 0.9, color: th.positive, lineHeight: 1.1}}>{n.hit ? "⚡" : "="}{n.value}</span>}
            </Pop>
          );
        })}
      </div>
    </div>
  );
};

const formula = (viz: Viz, cells: VizCell[], c: VizCell): string => {
  const vals = c.from.map((i) => cells[i].value);
  if (!vals.length) return `${c.label} = ${c.value}`;
  const plus = viz.plus ? ` + ${viz.plus}` : "";
  return `${c.label} = ${viz.combine === "sum" ? vals.join(" + ") : `${viz.combine}(${vals.join(", ")})`}${plus} = ${c.value}`;
};

const Table: React.FC<{viz: Viz; t: number}> = ({viz, t}) => {
  const th = useTheme();
  const cells = viz.cells ?? [], n = cells.length, gap = 10, cw = Math.min(120, (840 - gap * (n - 1)) / n);
  const filled = cells.filter((c) => c.t <= t), cur = filled[filled.length - 1];
  const src = cur && t - cur.t < 0.9 ? cur.from : [];
  return (
    <div>
      <Counter items={[{k: "FILLED", v: `${filled.length} / ${n}`, color: th.accent}]} />
      <div style={{display: "flex", gap, justifyContent: "center", marginTop: 90}}>
        {cells.map((c, i) => {
          const on = c.t <= t, isCur = cur === c, isSrc = src.includes(i);
          const col = isCur ? th.positive : isSrc ? th.accent : th.rule;
          return (
            <div key={i} style={{width: cw, textAlign: "center"}}>
              <div style={{fontFamily: MONO, fontSize: Math.max(16, cw * 0.2), color: th.muted, marginBottom: 8}}>{c.label.length <= 5 ? c.label : c.arg}</div>
              <div style={{height: cw * 1.05, borderRadius: 16, border: `3px solid ${on ? col : th.rule}`, background: isSrc ? th.accentSoft : on ? "rgba(61,220,151,0.10)" : th.surface, display: "grid", placeItems: "center",
                fontFamily: MONO, fontWeight: 700, fontSize: Math.max(24, cw * 0.4), color: on ? th.text : th.rule, boxShadow: isCur ? `0 0 26px ${th.positive}` : isSrc ? `0 0 18px ${th.accent}66` : "none",
                transform: `scale(${isCur ? 1.06 : 1})`}}>
                {on ? c.value : ""}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{textAlign: "center", fontFamily: MONO, fontWeight: 700, fontSize: 36, marginTop: 44, color: th.positive, minHeight: 50}}>{cur ? formula(viz, cells, cur) : ""}</div>
    </div>
  );
};

export const CodeViz: React.FC<{s: Scene; short: boolean}> = ({s}) => {
  const th = useTheme(), {t} = useT();
  const viz = s.viz;
  const active = activeLine(viz, t);
  return (
    <div style={{flex: 1, display: "flex", flexDirection: "column", gap: 26, minHeight: 0}}>
      <div style={{fontWeight: 700, fontSize: 50, lineHeight: 1.1, letterSpacing: -1, color: th.text}}>{s.title}</div>
      <Editor s={s} t={t} active={active} />
      {viz && (
        <div style={{flex: 1, border: `2px solid ${th.rule}`, borderRadius: 22, background: th.surface, padding: "18px 24px 20px", boxShadow: `0 0 40px ${th.accentSoft}`, overflow: "hidden", fontFamily: FONT}}>
          <div style={{fontWeight: 600, fontSize: 25, color: th.muted, marginBottom: 12, letterSpacing: 1}}>{viz.title}</div>
          {viz.kind === "calls" ? <Tree viz={viz} t={t} /> : <Table viz={viz} t={t} />}
        </div>
      )}
    </div>
  );
};
