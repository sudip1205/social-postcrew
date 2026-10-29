import React from "react";
import {AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {C, FONT, MONO} from "./theme";
import type {Box, Caption, Edge, Scene, Step, VideoProps} from "./types";

export const totalFrames = (p: VideoProps) =>
  Math.max(1, p.scenes.reduce((n, s) => n + Math.max(1, Math.round(s.seconds * p.fps)), 0));

const useT = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  return {t: f / fps, f, fps};
};

/** 0 -> 1 from second `at`, with a little overshoot. */
const usePop = (at: number) => {
  const {f, fps} = useT();
  return spring({frame: f - Math.round(at * fps), fps, config: {damping: 14, stiffness: 140}});
};
const useFade = (at: number, dur = 0.4) => {
  const {t} = useT();
  return interpolate(t, [at, at + dur], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
};

const Shell: React.FC<{p: VideoProps; s: Scene}> = ({p, s}) => {
  const short = p.format === "short";
  const {t} = useT();
  const drift = interpolate(t, [0, s.seconds], [0, 1]);
  return (
    <AbsoluteFill style={{background: C.bg, fontFamily: FONT, color: C.text}}>
      <AbsoluteFill style={{background: `radial-gradient(circle at ${30 + drift * 40}% ${15 + drift * 10}%, #21204d 0%, transparent 55%)`}} />
      <div style={{position: "absolute", inset: short ? "140px 64px 360px" : "70px 96px 170px", display: "flex", flexDirection: "column"}}>
        <Body p={p} s={s} />
      </div>
      <Captions p={p} caps={s.captions} />
    </AbsoluteFill>
  );
};

const Heading: React.FC<{text: string; short: boolean}> = ({text, short}) => {
  const o = useFade(0.1);
  return text ? <div style={{opacity: o, fontSize: short ? 60 : 52, fontWeight: 800, lineHeight: 1.1, marginBottom: short ? 48 : 32}}>{text}</div> : null;
};

const Body: React.FC<{p: VideoProps; s: Scene}> = ({p, s}) => {
  const short = p.format === "short";
  switch (s.layout) {
    case "title": return <Big text={s.title} short={short} accent />;
    case "statement": return <Big text={s.title} short={short} />;
    case "points": return <Points s={s} short={short} />;
    case "code": return <Code s={s} short={short} />;
    case "diagram":
    case "flow": return <Diagram s={s} short={short} flow={s.layout === "flow"} />;
    case "trace": return <Trace s={s} short={short} />;
  }
  return null;
};

const Big: React.FC<{text: string; short: boolean; accent?: boolean}> = ({text, short, accent}) => {
  const k = usePop(0.1);
  return (
    <div style={{flex: 1, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center",
      transform: `scale(${0.92 + 0.08 * k})`, opacity: Math.min(1, k)}}>
      <div style={{fontSize: short ? (accent ? 112 : 88) : (accent ? 104 : 80), fontWeight: 800, lineHeight: 1.08,
        color: accent ? C.text : C.text, textWrap: "balance" as never}}>
        {accent ? <span style={{borderBottom: `10px solid ${C.violet}`}}>{text}</span> : text}
      </div>
    </div>
  );
};

const Points: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const n = s.items.length || 1;
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{display: "flex", flexDirection: "column", gap: short ? 28 : 20, justifyContent: "center", flex: 1}}>
        {s.items.map((it, i) => <PointRow key={i} text={it} at={s.cues?.[i] ?? 0.3 + (i * s.seconds * 0.7) / n} short={short} />)}
      </div>
    </>
  );
};
const PointRow: React.FC<{text: string; at: number; short: boolean}> = ({text, at, short}) => {
  const k = usePop(at);
  return (
    <div style={{opacity: Math.min(1, k), transform: `translateX(${(1 - Math.min(1, k)) * -40}px)`, display: "flex", alignItems: "center", gap: 24,
      background: C.card, border: `2px solid ${C.border}`, borderRadius: 24, padding: short ? "30px 36px" : "22px 30px", fontSize: short ? 48 : 40, fontWeight: 600}}>
      <span style={{width: 18, height: 18, borderRadius: 9, background: C.violet, flex: "none"}} />{text}
    </div>
  );
};

const KEYWORDS = /\b(def|return|if|else|elif|for|while|in|not|and|or|import|from|class|const|let|var|function|new|true|false|True|False|None|null|async|await|break|continue)\b/g;
const Code: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const {t} = useT();
  const lines = s.code.replace(/\s+$/, "").split("\n");
  const shown = Math.ceil(interpolate(t, [0.2, Math.max(0.6, s.seconds * 0.8)], [0, lines.length], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}));
  const size = Math.min(short ? 42 : 38, (short ? 900 : 1700) / Math.max(12, ...lines.map((l) => l.length)) * 1.6);
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{background: C.code, border: `2px solid ${C.border}`, borderRadius: 24, padding: 36, fontFamily: MONO, fontSize: size, lineHeight: 1.5}}>
        <div style={{color: C.muted, fontSize: 24, marginBottom: 16}}>{s.language}</div>
        {lines.map((l, i) => (
          <div key={i} style={{opacity: i < shown ? 1 : 0, whiteSpace: "pre", color: C.text}}>
            {l.split(KEYWORDS).map((part, j) => (j % 2 ? <span key={j} style={{color: C.violet, fontWeight: 700}}>{part}</span> : part))}
          </div>
        ))}
      </div>
    </>
  );
};

type P = {x: number; y: number};
const Diagram: React.FC<{s: Scene; short: boolean; flow: boolean}> = ({s, short, flow}) => {
  const nodes = s.nodes ?? [], edges = s.edges ?? [];
  const W = short ? 952 : 1728, H = short ? 1100 : 640;
  const bw = short ? 520 : Math.min(300, (W - 60 * nodes.length) / Math.max(1, nodes.length)), bh = short ? 120 : 110;
  const pos: P[] = nodes.map((_, i) => short
    ? {x: W / 2, y: bh / 2 + (i * (H - bh)) / Math.max(1, nodes.length - 1 || 1)}
    : {x: bw / 2 + (i * (W - bw)) / Math.max(1, nodes.length - 1 || 1), y: H / 2});
  if (nodes.length === 1) pos[0] = {x: W / 2, y: H / 2};
  const {t} = useT();
  return (
    <>
      <Heading text={s.title} short={short} />
      <svg width={W} height={H} style={{overflow: "visible"}}>
        <defs>
          <marker id="ah" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill={C.violet} /></marker>
          <marker id="ahb" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill={C.amber} /></marker>
        </defs>
        {edges.map((e, i) => <EdgeView key={i} e={e} nodes={nodes} pos={pos} bw={bw} bh={bh} short={short} flow={flow} t={t}
          lane={edges.some((o) => o.from === e.to && o.to === e.from) ? (e.from < e.to ? -1 : 1) : 0} />)}
        {nodes.map((n, i) => <NodeView key={i} n={n} at={pos[i]} bw={bw} bh={bh} short={short} active={flow && edges.some((e) => (e.from === i || e.to === i) && t >= e.t && t < e.t + 1.4)} />)}
      </svg>
    </>
  );
};

const NodeView: React.FC<{n: Box; at: P; bw: number; bh: number; short: boolean; active: boolean}> = ({n, at, bw, bh, short, active}) => {
  const k = Math.min(1, usePop(n.t));
  return (
    <g transform={`translate(${at.x} ${at.y}) scale(${0.85 + 0.15 * k})`} opacity={k}>
      <rect x={-bw / 2} y={-bh / 2} width={bw} height={bh} rx={22} fill={C.card} stroke={active ? C.green : C.violet} strokeWidth={active ? 5 : 3} />
      <text textAnchor="middle" dominantBaseline="central" fill={C.text} fontSize={short ? 44 : 34} fontWeight={700} fontFamily={FONT}>{n.label}</text>
    </g>
  );
};

const EdgeView: React.FC<{e: Edge; nodes: Box[]; pos: P[]; bw: number; bh: number; short: boolean; flow: boolean; t: number; lane: number}> = ({e, pos, bw, bh, short, flow, t, lane}) => {
  const a = pos[e.from], b = pos[e.to];
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len, off = lane * 22;
  const nx = -uy * off, ny = ux * off;
  const reach = (u: number, v: number) => Math.min(Math.abs(u) > 1e-6 ? bw / 2 / Math.abs(u) : 1e9, Math.abs(v) > 1e-6 ? bh / 2 / Math.abs(v) : 1e9) + 6;
  const r = reach(ux, uy);
  const x1 = a.x + ux * r + nx, y1 = a.y + uy * r + ny, x2 = b.x - ux * r + nx, y2 = b.y - uy * r + ny;
  const grow = interpolate(t, [e.t, e.t + 0.6], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  if (t < e.t) return null;
  const back = e.from > e.to, col = back ? C.amber : C.violet;
  const px = x1 + (x2 - x1) * grow, py = y1 + (y2 - y1) * grow;
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  const pack = flow ? interpolate(t, [e.t + 0.3, e.t + 1.3], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}) : -1;
  return (
    <g>
      <line x1={x1} y1={y1} x2={px} y2={py} stroke={col} strokeWidth={5} strokeLinecap="round" markerEnd={grow > 0.98 ? `url(#${back ? "ahb" : "ah"})` : undefined} />
      {e.label && grow > 0.5 && (
        <g transform={`translate(${mx + (short ? 0 : 0)} ${my - (short ? 0 : 40) + (lane * (short ? 0 : 0))})`} opacity={Math.min(1, (grow - 0.5) * 2)}>
          <rect x={-e.label.length * (short ? 11 : 9) - 18} y={-24} width={e.label.length * (short ? 22 : 18) + 36} height={48} rx={24} fill={C.bg} stroke={col} strokeWidth={2} />
          <text textAnchor="middle" dominantBaseline="central" fill={C.text} fontSize={short ? 30 : 26} fontFamily={MONO}>{e.label}</text>
        </g>
      )}
      {pack >= 0 && pack <= 1 && <circle cx={x1 + (x2 - x1) * pack} cy={y1 + (y2 - y1) * pack} r={14} fill={C.green} />}
    </g>
  );
};

const Trace: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const {t} = useT();
  const cells = s.cells ?? [], steps = s.steps ?? [];
  const cur: Step | undefined = [...steps].reverse().find((st) => st.t <= t);
  const cw = Math.min(short ? 140 : 170, (short ? 952 : 1700) / Math.max(1, cells.length) - 16);
  const color = (i: number) => (cur?.found.includes(i) ? C.green : cur?.active.includes(i) ? C.amber : cur?.out.includes(i) ? "#3a3c4e" : C.border);
  const k = Math.min(1, usePop(0.2));
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{display: "flex", justifyContent: "center", gap: 14, marginTop: short ? 60 : 20, opacity: k}}>
        {cells.map((c, i) => (
          <div key={i} style={{width: cw, position: "relative"}}>
            <div style={{height: cw * 0.95, border: `4px solid ${color(i)}`, borderRadius: 18, background: C.card, display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: cw * 0.38, fontWeight: 700, fontFamily: MONO, opacity: cur?.out.includes(i) ? 0.45 : 1}}>{c}</div>
            <div style={{textAlign: "center", color: C.muted, fontSize: 24, marginTop: 6}}>{i}</div>
            <div style={{textAlign: "center", color: C.violet, fontWeight: 700, fontSize: 30, minHeight: 80}}>
              {(cur?.pointers ?? []).filter((p) => p.at === i).map((p) => <div key={p.name}>▲ {p.name}</div>)}
            </div>
          </div>
        ))}
      </div>
      {cur?.note && <div style={{textAlign: "center", fontSize: short ? 44 : 38, fontWeight: 600, marginTop: 24}}>{cur.note}</div>}
      {!!cur?.memo.length && (
        <div style={{display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap", marginTop: 28, fontFamily: MONO, fontSize: short ? 34 : 30}}>
          {cur.memo.map((m) => <span key={m} style={{background: C.card, border: `2px solid ${C.border}`, borderRadius: 14, padding: "8px 18px"}}>{m}</span>)}
        </div>
      )}
    </>
  );
};

const Captions: React.FC<{p: VideoProps; caps: Caption[]}> = ({p, caps}) => {
  const {t} = useT();
  const short = p.format === "short";
  const c = caps.find((x, i) => t >= x.start && (t < x.end || (i === caps.length - 1) || t < caps[i + 1].start));
  if (!c) return null;
  return (
    <div style={{position: "absolute", left: 64, right: 64, bottom: short ? 190 : 56, textAlign: "center"}}>
      <span style={{display: "inline-block", background: "rgba(11,12,18,0.82)", border: `2px solid ${C.border}`, borderRadius: 20, padding: "14px 30px",
        fontSize: short ? 56 : 44, fontWeight: 800, lineHeight: 1.2}}>{c.text}</span>
    </div>
  );
};

export const Video: React.FC<VideoProps> = (p) => {
  let from = 0;
  return (
    <AbsoluteFill>
      {p.scenes.map((s, i) => {
        const d = Math.max(1, Math.round(s.seconds * p.fps));
        const el = <Sequence key={i} from={from} durationInFrames={d}><Shell p={p} s={s} /></Sequence>;
        from += d;
        return el;
      })}
    </AbsoluteFill>
  );
};
