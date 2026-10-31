import React from "react";
import {AbsoluteFill, Sequence, interpolate} from "remotion";
import {FONT, MONO, ThemeContext, ease, keyWord, useProgress, useT, useTheme} from "./theme";
import {useFonts} from "./fonts";
import type {Box, Caption, Edge, Scene, Step, VideoProps} from "./types";

/*
 * The scenes follow postcrew/remotion/STYLE.md: a flat page, one accent colour, thin rules, slow eased reveals (never a bounce), the
 * colours of the look chosen in Settings (postcrew/render/looks.py). Python decides WHEN things happen; these only draw a frame.
 */

export const totalFrames = (p: VideoProps) =>
  Math.max(1, p.scenes.reduce((n, s) => n + Math.max(1, Math.round(s.seconds * p.fps)), 0));

/** One word that rises out of a mask, like type being set. */
const MaskWord: React.FC<{word: string; at: number; color: string; dur?: number}> = ({word, at, color, dur = 1.0}) => {
  const p = useProgress(at, dur);
  return (
    <span style={{display: "inline-block", overflow: "hidden", verticalAlign: "top", paddingBottom: "0.16em", marginBottom: "-0.16em", marginRight: "0.26em"}}>
      <span style={{display: "inline-block", transform: `translateY(${(1 - p) * 108}%)`, color}}>{word}</span>
    </span>
  );
};

const Headline: React.FC<{text: string; size: number; at?: number; step?: number; align?: "left" | "center"; accentKey?: boolean; keyAt?: number}> =
  ({text, size, at = 0.2, step = 0.14, align = "left", accentKey = true, keyAt}) => {
    const th = useTheme();
    const words = text.split(/\s+/).filter(Boolean), key = accentKey ? (keyAt ?? keyWord(words)) : -1;
    return (
      <div style={{fontSize: size, fontWeight: 700, lineHeight: 1.1, letterSpacing: -size * 0.028, textAlign: align}}>
        {words.map((w, i) => <MaskWord key={i} word={w} at={at + i * step} color={i === key ? th.highlight : th.text} />)}
      </div>
    );
  };

/** A thin rule that draws itself from the left. */
const Rule: React.FC<{at: number; width: number | string; thick?: number; color?: string; dur?: number}> = ({at, width, thick = 6, color, dur = 1.1}) => {
  const th = useTheme(), p = useProgress(at, dur);
  return <div style={{width, height: thick, background: color ?? th.accent, transformOrigin: "left center", transform: `scaleX(${p})`}} />;
};

const Heading: React.FC<{text: string; short: boolean}> = ({text, short}) =>
  text ? (
    <div style={{marginBottom: short ? 56 : 36}}>
      <Headline text={text} size={short ? 64 : 54} accentKey={false} />
      <div style={{marginTop: 22}}><Rule at={0.5} width={short ? 96 : 84} thick={5} /></div>
    </div>
  ) : null;

const Shell: React.FC<{p: VideoProps; s: Scene}> = ({p, s}) => {
  const th = p.theme, short = p.format === "short";
  const {t} = useT();
  const fade = useProgress(0, 0.7);
  const push = 1 + 0.014 * Math.min(1, t / Math.max(1, s.seconds));   // a very slow push-in: the page is never fully still
  return (
    <AbsoluteFill style={{background: th.bg, fontFamily: FONT, color: th.text}}>
      <div style={{position: "absolute", inset: short ? "170px 96px 400px" : "90px 150px 190px", display: "flex", flexDirection: "column",
        opacity: fade, transform: `scale(${push})`, transformOrigin: "left center"}}>
        <Body p={p} s={s} />
      </div>
      <Captions p={p} caps={s.captions} />
    </AbsoluteFill>
  );
};

const Body: React.FC<{p: VideoProps; s: Scene}> = ({p, s}) => {
  const short = p.format === "short";
  if (s.closing) return <Closing s={s} short={short} />;
  switch (s.layout) {
    case "title": return <Statement text={s.title} short={short} big keyAt={s.key} />;
    case "statement": return <Statement text={s.title} short={short} keyAt={s.key} />;
    case "points": return <Points s={s} short={short} />;
    case "code": return <Code s={s} short={short} />;
    case "diagram":
    case "flow": return <Diagram s={s} short={short} flow={s.layout === "flow"} />;
    case "trace": return <Trace s={s} short={short} />;
  }
  return null;
};

const Statement: React.FC<{text: string; short: boolean; big?: boolean; keyAt?: number}> = ({text, short, big, keyAt}) => (
  <div style={{flex: 1, display: "flex", flexDirection: "column", justifyContent: "center"}}>
    <div style={{marginBottom: 44}}><Rule at={0.1} width={big ? 150 : 110} thick={big ? 9 : 6} /></div>
    <Headline text={text} size={short ? (big ? 132 : 98) : (big ? 112 : 86)} at={0.35} keyAt={keyAt} />
  </div>
);

/** The closing line: "Like · Comment · Share", each part appears when the voice says it, after a quiet beat. */
const Closing: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const th = useTheme();
  return (
    <div style={{flex: 1, display: "flex", flexDirection: "column", justifyContent: "center"}}>
      <div style={{marginBottom: 56}}><Rule at={0.15} width={short ? 150 : 130} thick={7} dur={1.4} /></div>
      {s.items.map((part, i) => {
        const at = s.cues?.[i] ?? 0.8 + i * 0.8;
        return (
          <div key={i}>
            <Rule at={at - 0.1} width="100%" thick={2} color={th.rule} dur={1.0} />
            <div style={{padding: short ? "30px 0" : "20px 0", fontSize: short ? 124 : 96, fontWeight: 700, letterSpacing: -4, lineHeight: 1.05}}>
              <MaskWord word={part} at={at} color={i === s.items.length - 1 ? th.highlight : th.text} dur={1.1} />
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Points: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const n = s.items.length || 1;
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{flex: 1, display: "flex", flexDirection: "column", justifyContent: "center"}}>
        {s.items.map((it, i) => <PointRow key={i} n={i + 1} text={it} at={s.cues?.[i] ?? 0.5 + (i * s.seconds * 0.7) / n} short={short} />)}
      </div>
    </>
  );
};
const PointRow: React.FC<{n: number; text: string; at: number; short: boolean}> = ({n, text, at, short}) => {
  const th = useTheme(), p = useProgress(at, 1.0);
  return (
    <div style={{display: "flex", alignItems: "baseline", gap: 32, padding: short ? "44px 0" : "22px 0", borderTop: `2px solid ${th.rule}`,
      opacity: p, transform: `translateY(${(1 - p) * 26}px)`}}>
      <span style={{fontFamily: MONO, fontWeight: 700, fontSize: short ? 40 : 28, color: th.accent, minWidth: 80}}>{String(n).padStart(2, "0")}</span>
      <span style={{fontSize: short ? 62 : 42, fontWeight: 600, lineHeight: 1.2, letterSpacing: -1}}>{text}</span>
    </div>
  );
};

const KEYWORDS = /\b(def|return|if|else|elif|for|while|in|not|and|or|import|from|class|const|let|var|function|new|true|false|True|False|None|null|async|await|break|continue)\b/g;
const Code: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const th = useTheme(), {t} = useT();
  const lines = s.code.replace(/\s+$/, "").split("\n");
  const shown = interpolate(t, [0.5, Math.max(1.2, s.seconds * 0.8)], [0, lines.length], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const size = Math.min(short ? 50 : 36, ((short ? 800 : 1500) / Math.max(12, ...lines.map((l) => l.length))) * 1.65);
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{background: th.surface, border: `2px solid ${th.rule}`, borderRadius: 14, padding: short ? "36px 40px" : "28px 36px", fontFamily: MONO, fontSize: size, lineHeight: 1.6}}>
        <div style={{color: th.muted, fontSize: 22, letterSpacing: 2, textTransform: "uppercase", marginBottom: 18}}>{s.language}</div>
        {lines.map((l, i) => {
          const a = Math.max(0, Math.min(1, shown - i));
          return (
            <div key={i} style={{display: "flex", gap: 28, whiteSpace: "pre", opacity: ease(a), transform: `translateY(${(1 - ease(a)) * 10}px)`}}>
              <span style={{color: th.muted, minWidth: 34, textAlign: "right"}}>{i + 1}</span>
              <span>{l.split(KEYWORDS).map((part, j) => (j % 2 ? <span key={j} style={{color: th.accent, fontWeight: 700}}>{part}</span> : part))}</span>
            </div>
          );
        })}
      </div>
    </>
  );
};

type P = {x: number; y: number};
const Diagram: React.FC<{s: Scene; short: boolean; flow: boolean}> = ({s, short, flow}) => {
  const nodes = s.nodes ?? [], edges = s.edges ?? [];
  const W = short ? 888 : 1620, H = short ? 1060 : 600;
  const bw = short ? 640 : Math.min(290, (W - 70 * nodes.length) / Math.max(1, nodes.length)), bh = short ? 150 : 104;
  const pos: P[] = nodes.map((_, i) => short
    ? {x: W / 2, y: bh / 2 + (i * (H - bh)) / Math.max(1, nodes.length - 1 || 1)}
    : {x: bw / 2 + (i * (W - bw)) / Math.max(1, nodes.length - 1 || 1), y: H / 2});
  if (nodes.length === 1) pos[0] = {x: W / 2, y: H / 2};
  const th = useTheme(), {t} = useT();
  // in a wide video the labels sit on the arrows; when a label is wider than the gap between two boxes they go above and below the row instead
  const gap = short || nodes.length < 2 ? 0 : (W - bw * nodes.length) / (nodes.length - 1);
  const tight = !short && edges.some((e) => e.label.length * 14 + 70 > gap - 16);
  return (
    <>
      <Heading text={s.title} short={short} />
      <svg width={W} height={H} style={{overflow: "visible"}}>
        <defs>
          <marker id="ah" markerWidth="12" markerHeight="12" refX="9" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 z" fill={th.accent} /></marker>
        </defs>
        {edges.map((e, i) => <EdgeView key={i} n={i + 1} e={e} pos={pos} bw={bw} bh={bh} short={short} flow={flow} t={t} tight={tight}
          lane={edges.some((o) => o.from === e.to && o.to === e.from) ? 1 : 0} />)}
        {nodes.map((n, i) => <NodeView key={i} n={n} at={pos[i]} bw={bw} bh={bh} short={short}
          active={flow && edges.some((e) => (e.from === i || e.to === i) && t >= e.t && t < e.t + 1.6)} />)}
      </svg>
    </>
  );
};

const NodeView: React.FC<{n: Box; at: P; bw: number; bh: number; short: boolean; active: boolean}> = ({n, at, bw, bh, short, active}) => {
  const th = useTheme(), p = useProgress(n.t, 0.9);
  return (
    <g transform={`translate(${at.x} ${at.y + (1 - p) * 16})`} opacity={p}>
      <rect x={-bw / 2} y={-bh / 2} width={bw} height={bh} rx={12} fill={active ? th.accentSoft : th.surface} stroke={active ? th.accent : th.text} strokeWidth={active ? 4 : 2.5} />
      <text textAnchor="middle" dominantBaseline="central" fill={th.text} fontSize={short ? 52 : 34} fontWeight={600} fontFamily={FONT} letterSpacing={-0.8}>{n.label}</text>
    </g>
  );
};

const EdgeView: React.FC<{n: number; e: Edge; pos: P[]; bw: number; bh: number; short: boolean; flow: boolean; t: number; lane: number; tight?: boolean}> = ({n, e, pos, bw, bh, short, flow, t, lane, tight}) => {
  const th = useTheme();
  const a = pos[e.from], b = pos[e.to];
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len, off = lane * 24;
  const nx = -uy * off, ny = ux * off;
  const reach = (u: number, v: number) => Math.min(Math.abs(u) > 1e-6 ? bw / 2 / Math.abs(u) : 1e9, Math.abs(v) > 1e-6 ? bh / 2 / Math.abs(v) : 1e9) + 8;
  const r = reach(ux, uy);
  const x1 = a.x + ux * r + nx, y1 = a.y + uy * r + ny, x2 = b.x - ux * r + nx, y2 = b.y - uy * r + ny;
  const grow = interpolate(t, [e.t, e.t + 0.9], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
  if (t < e.t) return null;
  const px = x1 + (x2 - x1) * grow, py = y1 + (y2 - y1) * grow;
  // an arrow and its reply share two boxes: each is drawn to its own side of the line (the offset is relative to its own direction), and
  // the labels never overlap: in a vertical video they sit at 32% of their own arrows (one near each box); in a wide one the arrow's label
  // is below its line and the reply's label above its own
  const lt = lane && short ? 0.32 : 0.5;
  const mx = x1 + (x2 - x1) * lt, my = y1 + (y2 - y1) * lt;
  const pack = flow ? interpolate(t, [e.t + 0.5, e.t + 1.8], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease}) : -1;
  const lab = e.label ? e.label.length * (short ? 17 : 14) + 70 : 0;
  return (
    <g>
      <line x1={x1} y1={y1} x2={px} y2={py} stroke={th.accent} strokeWidth={4} strokeLinecap="round" strokeDasharray={e.from > e.to ? "3 12" : undefined}
        markerEnd={grow > 0.98 ? "url(#ah)" : undefined} />
      {grow > 0.55 && (
        <g transform={`translate(${mx} ${my + (short ? 0 : tight ? (lane && e.from < e.to ? bh / 2 + 40 : -(bh / 2 + 40)) : lane ? (e.from < e.to ? 50 : -50) : -38)})`} opacity={Math.min(1, (grow - 0.55) * 2.2)}>
          <rect x={-lab / 2} y={-26} width={lab || 52} height={52} rx={26} fill={th.bg} stroke={th.rule} strokeWidth={2} />
          <circle cx={lab ? -lab / 2 + 26 : 0} cy={0} r={15} fill={th.accent} />
          <text x={lab ? -lab / 2 + 26 : 0} y={1} textAnchor="middle" dominantBaseline="central" fill={th.bg} fontSize={19} fontWeight={700} fontFamily={MONO}>{n}</text>
          {e.label && <text x={14} y={1} textAnchor="middle" dominantBaseline="central" fill={th.text} fontSize={short ? 27 : 23} fontFamily={MONO}>{e.label}</text>}
        </g>
      )}
      {pack >= 0 && pack <= 1 && <circle cx={x1 + (x2 - x1) * pack} cy={y1 + (y2 - y1) * pack} r={13} fill={th.accent} />}
    </g>
  );
};

const Trace: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const th = useTheme(), {t} = useT();
  const cells = s.cells ?? [], steps = s.steps ?? [];
  const cur: Step | undefined = [...steps].reverse().find((st) => st.t <= t);
  const cw = Math.min(short ? 176 : 160, (short ? 888 : 1620) / Math.max(1, cells.length) - 18);
  const p = useProgress(0.4, 1.0);
  const look = (i: number) => cur?.found.includes(i) ? {border: th.positive, fill: `${th.positive}22`, op: 1}
    : cur?.active.includes(i) ? {border: th.accent, fill: th.accentSoft, op: 1}
    : cur?.out.includes(i) ? {border: th.rule, fill: "transparent", op: 0.4} : {border: th.text, fill: th.surface, op: 1};
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{display: "flex", justifyContent: "center", gap: 16, marginTop: short ? 50 : 16, opacity: p}}>
        {cells.map((c, i) => {
          const l = look(i);
          return (
            <div key={i} style={{width: cw, opacity: l.op}}>
              <div style={{height: cw * 0.95, border: `${l.border === th.text ? 2.5 : 4}px solid ${l.border}`, borderRadius: 12, background: l.fill, display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: cw * 0.36, fontWeight: 700, fontFamily: MONO}}>{c}</div>
              <div style={{textAlign: "center", color: th.muted, fontSize: 24, fontFamily: MONO, marginTop: 10}}>{i}</div>
              <div style={{textAlign: "center", color: th.accent, fontWeight: 700, fontSize: 28, fontFamily: MONO, minHeight: 84}}>
                {(cur?.pointers ?? []).filter((q) => q.at === i).map((q) => <div key={q.name}>▲ {q.name}</div>)}
              </div>
            </div>
          );
        })}
      </div>
      {cur?.note && <div style={{textAlign: "center", fontSize: short ? 56 : 38, fontWeight: 600, letterSpacing: -0.8, marginTop: 36}}>{cur.note}</div>}
      {!!cur?.memo.length && (
        <div style={{display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap", marginTop: 30, fontFamily: MONO, fontSize: short ? 32 : 28}}>
          {cur.memo.map((m) => <span key={m} style={{border: `2px solid ${th.rule}`, borderRadius: 10, padding: "8px 18px"}}>{m}</span>)}
        </div>
      )}
    </>
  );
};

/** Captions: plain text on the page, a few calm lines at a time. No box, no colour. */
const Captions: React.FC<{p: VideoProps; caps: Caption[]}> = ({p, caps}) => {
  const {t} = useT();
  const short = p.format === "short";
  const i = caps.findIndex((x, k) => t >= x.start && (t < x.end || k === caps.length - 1 || t < caps[k + 1].start));
  if (i < 0) return null;
  const c = caps[i], a = interpolate(t, [c.start, c.start + 0.3], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <div style={{position: "absolute", left: short ? 96 : 150, right: short ? 96 : 150, bottom: short ? 200 : 62, textAlign: "center", opacity: a}}>
      <span style={{fontSize: short ? 52 : 40, fontWeight: 600, lineHeight: 1.3, letterSpacing: -0.5, color: p.theme.text}}>{c.text}</span>
    </div>
  );
};

export const Video: React.FC<VideoProps> = (p) => {
  useFonts();
  let from = 0;
  return (
    <ThemeContext.Provider value={p.theme}>
      <AbsoluteFill style={{background: p.theme.bg}}>
        {p.scenes.map((s, i) => {
          const d = Math.max(1, Math.round(s.seconds * p.fps));
          const el = <Sequence key={i} from={from} durationInFrames={d}><Shell p={p} s={s} /></Sequence>;
          from += d;
          return el;
        })}
      </AbsoluteFill>
    </ThemeContext.Provider>
  );
};
