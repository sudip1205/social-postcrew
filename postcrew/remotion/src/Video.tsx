import React from "react";
import {AbsoluteFill, Sequence, interpolate} from "remotion";
import {FONT, MONO, ThemeContext, ease, keyWord, useProgress, useT, useTheme} from "./theme";
import {useFonts} from "./fonts";
import type {Box, Caption, Edge, Scene, Step, Svg, VideoProps} from "./types";
import {Colored, EXT} from "./code";
import {CodeViz} from "./CodeViz";
import {Stairs} from "./Stairs";
import {Grid} from "./Grid";

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
    <AbsoluteFill style={{background: th.name === "neon" ? `radial-gradient(ellipse 80% 40% at 50% 38%, ${th.accentSoft}, transparent 70%), ${th.bg}` : th.bg, fontFamily: FONT, color: th.text}}>
      <div style={{position: "absolute", inset: short ? "170px 96px 400px" : "90px 150px 190px", display: "flex", flexDirection: "column",
        opacity: fade, transform: `scale(${push})`, transformOrigin: "left center"}}>
        <Body p={p} s={s} />
      </div>
      <Captions p={p} caps={s.captions} />
    </AbsoluteFill>
  );
};

/** A clipart: an icon or colour picture drawn from its SVG markup (render/iconlib.py). Line icons take the page's colour. */
const Glyph: React.FC<{svg?: Svg | null; size: number; color?: string}> = ({svg, size, color}) => {
  const th = useTheme();
  if (!svg) return null;
  return <svg width={size} height={(size * svg.h) / svg.w} viewBox={`0 0 ${svg.w} ${svg.h}`} style={{color: color ?? th.text, flexShrink: 0}}
    dangerouslySetInnerHTML={{__html: svg.body}} />;
};

/** The picture beside a words scene: a big clipart on a soft disc, beside the text in a wide video and above it in a vertical one. */
const WithClip: React.FC<{clip?: Svg; short: boolean; children: React.ReactNode}> = ({clip, short, children}) => {
  const th = useTheme(), p = useProgress(0.35, 1.0);
  if (!clip) return <>{children}</>;
  const d = short ? 360 : 420;
  const disc = (
    <div style={{width: d, height: d, borderRadius: d, background: th.accentSoft, display: "flex", alignItems: "center", justifyContent: "center",
      opacity: p, transform: `scale(${0.9 + 0.1 * p})`, flexShrink: 0}}>
      <Glyph svg={clip} size={d * 0.56} color={th.accent} />
    </div>
  );
  return short
    ? <div style={{flex: 1, display: "flex", flexDirection: "column", gap: 40}}><div style={{display: "flex", justifyContent: "flex-start"}}>{disc}</div>{children}</div>
    : <div style={{flex: 1, display: "flex", alignItems: "center", gap: 90}}><div style={{flex: 1, display: "flex", flexDirection: "column", alignSelf: "stretch"}}>{children}</div>{disc}</div>;
};

const Body: React.FC<{p: VideoProps; s: Scene}> = ({p, s}) => {
  const short = p.format === "short";
  if (s.closing) return <Closing s={s} short={short} />;
  switch (s.layout) {
    case "title": return <WithClip clip={s.clip} short={short}><Statement text={s.title} short={short} big keyAt={s.key} /></WithClip>;
    case "statement": return <WithClip clip={s.clip} short={short}><Statement text={s.title} short={short} keyAt={s.key} /></WithClip>;
    case "points": return <WithClip clip={s.clip} short={short}><Points s={s} short={short} /></WithClip>;
    case "code": return <Code s={s} short={short} />;
    case "codeviz": return <CodeViz s={s} short={short} />;
    case "paths": return <Stairs s={s} short={short} />;
    case "grid": return s.grid ? <Grid s={s} short={short} /> : <Statement text={s.title} short={short} keyAt={s.key} />;
    case "diagram":
    case "flow": return <Diagram s={s} short={short} flow={s.layout === "flow"} />;
    case "trace": return <Trace s={s} short={short} />;
    case "stat": return <Stat s={s} short={short} />;
  }
  return null;
};

const Statement: React.FC<{text: string; short: boolean; big?: boolean; keyAt?: number}> = ({text, short, big, keyAt}) => (
  <div style={{flex: 1, display: "flex", flexDirection: "column", justifyContent: "center"}}>
    <div style={{marginBottom: 44}}><Rule at={0.1} width={big ? 150 : 110} thick={big ? 9 : 6} /></div>
    <Headline text={text} size={short ? (big ? 132 : 98) : (big ? 112 : 86)} at={0.35} keyAt={keyAt} />
  </div>
);

/** The closing card: real-looking buttons (Like, Comment, Share, Subscribe). Each appears, and is pressed when the voice says its word: it dips, ripples
 *  and changes state (a filled thumb with a +1, a ringing bell that turns "Subscribed"). */
const PressButton: React.FC<{b: {label: string; kind: string; svg?: Svg | null}; at: number; short: boolean; index: number}> = ({b, at, short, index}) => {
  const th = useTheme(), {t} = useT();
  const enter = useProgress(Math.max(0, at - 0.9 + index * 0.05), 0.7);
  const dt = t - at, press = 0.16;
  const down = dt < 0 ? 0 : dt < press ? dt / press : dt < press + 0.4 ? 1 - (dt - press) / 0.4 : 0;
  const pressed = dt >= press;
  const scale = (0.9 + 0.1 * enter) * (1 - 0.08 * down) * (pressed && dt < press + 0.5 ? 1 + 0.04 * Math.sin(((dt - press) / 0.5) * Math.PI) : 1);
  const hot = b.kind === "subscribe" ? th.highlight : th.accent;
  const ring = dt >= press && dt < press + 1.1 ? (dt - press) / 1.1 : -1;
  const wiggle = b.kind === "subscribe" && pressed && dt < press + 1.2 ? Math.sin((dt - press) * 26) * 22 * (1 - (dt - press) / 1.2) : 0;
  const pop = b.kind === "like" && pressed && dt < press + 0.9 ? (dt - press) / 0.9 : -1;
  const h = short ? 132 : 104, isz = short ? 60 : 46, fs = short ? 54 : 42;
  const label = b.kind === "subscribe" && pressed ? "Subscribed" : b.label;
  return (
    <div style={{position: "relative", opacity: enter, transform: `translateY(${(1 - enter) * 30}px) scale(${scale})`}}>
      {ring >= 0 && <div style={{position: "absolute", inset: 0, borderRadius: h, border: `4px solid ${hot}`, opacity: 0.6 * (1 - ring), transform: `scale(${1 + ring * 0.35})`}} />}
      <div style={{height: h, padding: `0 ${short ? 56 : 44}px`, borderRadius: h, display: "flex", alignItems: "center", justifyContent: "center", gap: 22,
        background: pressed ? hot : th.surface, border: `3px solid ${pressed ? hot : th.text}`, color: pressed ? th.bg : th.text, boxShadow: pressed ? "none" : `0 6px 0 ${th.rule}`,
        fontWeight: 700, fontSize: fs, letterSpacing: -1, whiteSpace: "nowrap"}}>
        <svg width={isz} height={(isz * (b.svg?.h ?? 24)) / (b.svg?.w ?? 24)} viewBox={`0 0 ${b.svg?.w ?? 24} ${b.svg?.h ?? 24}`} style={{color: "inherit", transform: `rotate(${wiggle}deg)`, transformOrigin: "50% 15%"}}
          fill={pressed && b.kind === "like" ? "currentColor" : "none"} dangerouslySetInnerHTML={{__html: b.svg?.body ?? ""}} />
        <span>{label}</span>
      </div>
      {pop >= 0 && <div style={{position: "absolute", right: 28, top: -10 - pop * 60, opacity: 1 - pop, fontFamily: MONO, fontWeight: 700, fontSize: short ? 44 : 34, color: hot}}>+1</div>}
    </div>
  );
};
const Closing: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const buttons = s.buttons ?? s.items.map((x) => ({label: x, kind: x.toLowerCase(), svg: null}));
  return (
    <div style={{flex: 1, display: "flex", flexDirection: short ? "column" : "row", flexWrap: "wrap", alignItems: "center", justifyContent: "center", gap: short ? 44 : 40}}>
      {buttons.map((bt, i) => <PressButton key={i} b={bt} at={s.cues?.[i] ?? 0.8 + i * 0.8} short={short} index={i} />)}
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

/** A code scene drawn as an editor window: title bar, a file tab, line numbers, the line being typed highlighted with a blinking caret, and, when the
 *  scene has output lines in "items", a terminal panel that prints them once the code is typed. */
const Code: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const th = useTheme(), {t} = useT();
  const lines = s.code.replace(/\s+$/, "").split("\n");
  const typeEnd = Math.max(1.2, s.seconds * (s.items?.length ? 0.55 : 0.8));
  const shown = interpolate(t, [0.5, typeEnd], [0, lines.length], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  // readable on a phone first: never under 38 px on a Short (a long line wraps, its indent kept) rather than shrinking the whole file
  const size = Math.max(short ? 38 : 28, Math.min(short ? 50 : 36, ((short ? 780 : 1380) / Math.max(12, ...lines.map((l) => l.length))) * 1.65));
  const file = /\.\w{1,5}$/.test(s.title) ? s.title : `main.${EXT[(s.language || "").toLowerCase()] ?? "txt"}`;
  const cur = Math.min(lines.length - 1, Math.floor(shown)), done = shown >= lines.length, caret = Math.floor(t * 2.4) % 2 === 0;
  const out = s.items ?? [], termStart = typeEnd + 0.4;
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{flex: 1, display: "flex", flexDirection: "column", justifyContent: "center"}}>
      <div style={{border: `2px solid ${th.rule}`, borderRadius: 16, overflow: "hidden", background: th.surface}}>
        <div style={{height: 52, display: "flex", alignItems: "center", gap: 10, padding: "0 20px", background: th.accentSoft, borderBottom: `2px solid ${th.rule}`}}>
          {[0, 1, 2].map((i) => <span key={i} style={{width: 14, height: 14, borderRadius: 14, background: th.muted, opacity: 0.6}} />)}
          <span style={{marginLeft: 18, fontFamily: MONO, fontSize: 20, color: th.muted}}>{file}</span>
          <span style={{marginLeft: "auto", fontFamily: MONO, fontSize: 18, color: th.muted, letterSpacing: 2, textTransform: "uppercase"}}>{s.language}</span>
        </div>
        <div style={{padding: short ? "28px 36px" : "22px 30px", fontFamily: MONO, fontSize: size, lineHeight: 1.6}}>
          {lines.map((l, i) => {
            const a = Math.max(0, Math.min(1, shown - i)), active = i === cur && !done;
            return (
              <div key={i} style={{display: "flex", gap: 22, whiteSpace: "pre-wrap", wordBreak: "break-word", opacity: ease(a), background: active ? th.accentSoft : "transparent", margin: "0 -14px", padding: "0 14px", borderRadius: 6,
                transform: `translateY(${(1 - ease(a)) * 10}px)`}}>
                <span style={{color: th.muted, minWidth: 34, textAlign: "right", opacity: 0.8}}>{i + 1}</span>
                <span style={{flex: 1, minWidth: 0}}><Colored line={l} />{active && caret && <span style={{display: "inline-block", width: size * 0.5, height: size * 1.05, background: th.accent, marginLeft: 3, verticalAlign: "text-bottom"}} />}</span>
              </div>
            );
          })}
        </div>
        {out.length > 0 && (
          <div style={{borderTop: `2px solid ${th.rule}`, padding: short ? "20px 36px 26px" : "16px 30px 22px", fontFamily: MONO, fontSize: size * 0.82, lineHeight: 1.55, opacity: ease(Math.min(1, Math.max(0, (t - termStart + 0.3) / 0.5)))}}>
            <div style={{color: th.muted, fontSize: 17, letterSpacing: 3, textTransform: "uppercase", marginBottom: 10}}>Terminal</div>
            {out.map((o, i) => {
              const at = termStart + i * 0.55, a = Math.max(0, Math.min(1, (t - at) / 0.3));
              return <div key={i} style={{display: "flex", gap: 14, whiteSpace: "pre", opacity: ease(a), color: i === 0 ? th.text : th.muted}}><span style={{color: th.accent}}>{i === 0 ? "$" : ">"}</span><span>{o}</span></div>;
            })}
          </div>
        )}
      </div>
      </div>
    </>
  );
};

/** A big number that counts up, with an optional row of icons showing "a of b" (for example 7 of 10 highlighted). */
const Stat: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const th = useTheme(), {t} = useT();
  const value = s.items[0] ?? "", caption = s.items[1] ?? "";
  const m = value.match(/^([^\d]*)([\d,]*\.?\d+)(.*)$/);
  const start = s.cues?.[0] ?? 0.4, p = ease(Math.max(0, Math.min(1, (t - start) / 1.6)));
  const target = m ? parseFloat(m[2].replace(/,/g, "")) : 0, decimals = m && m[2].includes(".") ? m[2].split(".")[1].length : 0;
  const shownNum = m ? (target * p).toLocaleString("en-US", {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) : "";
  const [a, b] = [parseInt(s.cells?.[0] ?? "0", 10) || 0, parseInt(s.cells?.[1] ?? "0", 10) || 0], n = Math.min(b, 20);
  const lit = Math.round((a / Math.max(1, b)) * n);
  // The number is sized from its FINAL text (not the counting one, so it never jumps) to fit the content width: "2,692,537" at the full 250 px
  // ran off the right edge. Inter ExtraBold: a digit or letter is about 0.62 em, a comma, dot or space about 0.3 em, less the tight tracking.
  const finalText = m ? `${m[1]}${target.toLocaleString("en-US", {minimumFractionDigits: decimals, maximumFractionDigits: decimals})}${m[3]}` : value;
  const ems = [...finalText].reduce((w, c) => w + (/[,.\s'’]/.test(c) ? 0.3 : 0.62), 0);
  const maxSize = short ? 250 : 230, contentWidth = short ? 1080 - 2 * 96 : 1920 - 2 * 150;
  const numSize = Math.max(90, Math.min(maxSize, Math.floor((0.94 * contentWidth) / Math.max(1, ems - (finalText.length * 6) / maxSize))));
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: short ? 40 : 26}}>
        <div style={{fontWeight: 800, letterSpacing: -6, lineHeight: 1, whiteSpace: "nowrap", color: th.highlight, fontSize: numSize, opacity: ease(Math.min(1, t / 0.5))}}>
          {m ? <>{m[1]}{shownNum}{m[3]}</> : value}
        </div>
        {caption && <div style={{fontSize: short ? 56 : 44, fontWeight: 600, color: th.text, opacity: ease(Math.max(0, Math.min(1, (t - start - 0.6) / 0.6)))}}>{caption}</div>}
        {n > 0 && (
          <div style={{display: "flex", flexWrap: "wrap", gap: short ? 22 : 18}}>
            {Array.from({length: n}).map((_, i) => {
              const on = i < lit, at = start + 0.8 + i * 0.07, ap = ease(Math.max(0, Math.min(1, (t - at) / 0.4)));
              return (
                <div key={i} style={{opacity: ap, transform: `scale(${0.6 + 0.4 * ap})`, color: on ? th.highlight : th.muted}}>
                  {s.clip ? <Glyph svg={s.clip} size={short ? 76 : 62} color={on ? th.highlight : th.muted} /> : <div style={{width: short ? 60 : 48, height: short ? 60 : 48, borderRadius: 12, background: on ? th.highlight : th.rule}} />}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
};

type P = {x: number; y: number};
/** Where each box goes. A plain chain (each box passes to one next box) keeps the single row (wide) or column (vertical). Anything else, like a load balancer
 *  handing requests to several servers, is laid out in layers: who sends is above, who receives is below, so no arrow crosses a box. */
function layout(nodes: Box[], edges: Edge[], short: boolean, W: number, H: number) {
  const n = nodes.length, pairs = new Set(edges.map((e) => `${e.from}>${e.to}`));
  const fwd = edges.filter((e) => !(e.from > e.to && pairs.has(`${e.to}>${e.from}`)));   // a reply goes back along its request: it is not a new step
  const out: number[] = Array(n).fill(0), inn: number[] = Array(n).fill(0);
  new Set(fwd.map((e) => `${e.from}>${e.to}`)).forEach((k) => { const [f, t] = k.split(">").map(Number); out[f]++; inn[t]++; });
  const chain = n < 3 || (out.every((x) => x <= 1) && inn.every((x) => x <= 1));
  const hasIcon = nodes.some((x) => x.svg);
  if (chain) {
    const bw = short ? 640 : Math.max(190, Math.min(340, (W - 112 * (n - 1)) / Math.max(1, n))), bh = short ? 150 : (hasIcon ? 190 : 150);
    const pos: P[] = nodes.map((_, i) => short ? {x: W / 2, y: bh / 2 + (i * (H - bh)) / Math.max(1, n - 1 || 1)} : {x: bw / 2 + (i * (W - bw)) / Math.max(1, n - 1 || 1), y: H / 2});
    if (n === 1) pos[0] = {x: W / 2, y: H / 2};
    return {pos, bw, bh, layered: false};
  }
  const depth: number[] = Array(n).fill(0);
  for (let it = 0; it < n; it++) fwd.forEach((e) => { if (depth[e.to] < depth[e.from] + 1) depth[e.to] = depth[e.from] + 1; });
  const rows = Math.max(...depth) + 1, perRow = Array.from({length: rows}, (_, r) => nodes.map((_, i) => i).filter((i) => depth[i] === r)), widest = Math.max(...perRow.map((r) => r.length));
  const bw = short ? Math.min(640, W / widest - 28) : Math.max(180, Math.min(340, W / widest - 70));
  const bh = Math.min(short ? 150 : (hasIcon ? 190 : 150), (H - (rows - 1) * (short ? 100 : 112)) / rows);
  const pos: P[] = Array(n).fill(null).map(() => ({x: 0, y: 0}));
  perRow.forEach((row, r) => row.forEach((i, j) => { pos[i] = {x: ((j + 0.5) * W) / row.length, y: rows === 1 ? H / 2 : bh / 2 + (r * (H - bh)) / (rows - 1)}; }));
  return {pos, bw, bh, layered: true};
}

const Diagram: React.FC<{s: Scene; short: boolean; flow: boolean}> = ({s, short, flow}) => {
  const nodes = s.nodes ?? [], edges = s.edges ?? [];
  const W = short ? 888 : 1620, H = short ? 1060 : 680;
  const {pos, bw, bh, layered} = layout(nodes, edges, short, W, H);
  const th = useTheme(), {t} = useT();
  // in a wide chain the labels sit on the arrows; when a label is wider than the gap between two boxes they go above and below the row instead
  const gap = short || nodes.length < 2 || layered ? 0 : (W - bw * nodes.length) / (nodes.length - 1);
  const tight = !short && !layered && edges.some((e) => e.label.length * 16 + 70 > gap - 16);
  return (
    <>
      <Heading text={s.title} short={short} />
      <svg width={W} height={H} style={{overflow: "visible"}}>
        <defs>
          <marker id="ah" markerWidth="12" markerHeight="12" refX="9" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 z" fill={th.accent} /></marker>
        </defs>
        {edges.map((e, i) => <EdgeView key={i} n={i + 1} e={e} pos={pos} bw={bw} bh={bh} short={short} flow={flow} t={t} tight={tight} layered={layered}
          lane={edges.some((o) => o.from === e.to && o.to === e.from) ? 1 : 0} />)}
        {nodes.map((n, i) => <NodeView key={i} n={n} at={pos[i]} bw={bw} bh={bh} short={short}
          active={flow && edges.some((e) => (e.from === i || e.to === i) && t >= e.t && t < e.t + 1.6)} />)}
      </svg>
    </>
  );
};

const NodeView: React.FC<{n: Box; at: P; bw: number; bh: number; short: boolean; active: boolean}> = ({n, at, bw, bh, short, active}) => {
  const th = useTheme(), p = useProgress(n.t, 0.9);
  // a long label in a wide video goes on two lines so it can be big; the size fits the longest line to the box
  const words = n.label.split(" "), half = Math.ceil(words.length / 2);
  const lines = (!short || bw < 420) && n.label.length > 9 && words.length > 1 ? [words.slice(0, half).join(" "), words.slice(half).join(" ")] : [n.label];
  const narrow = bw < 420, icon = n.svg ?? null, isz = short && !narrow ? 84 : bh < 170 ? 46 : 58;   // an icon sits above the label in a wide box and to the left of it in a vertical one
  const room = icon && short && !narrow ? bw - isz - 90 : bw - 40;
  const fs = short && !narrow ? 52 : Math.max(24, Math.min(icon ? (bh < 170 ? 31 : 40) : 48, room / (Math.max(...lines.map((l) => l.length)) * 0.58)));
  const lx = icon && short && !narrow ? (isz + 24) / 2 : 0, ly0 = icon && (!short || narrow) ? (bh < 170 && lines.length > 1 ? 24 : 34) : 0;
  const down = n.state === "down", busy = n.state === "busy", {t} = useT();
  const col = down ? th.muted : busy ? th.highlight : active ? th.accent : th.text;
  const pulse = busy ? 0.5 + 0.5 * Math.sin(t * 6) : 0;
  return (
    <g transform={`translate(${at.x} ${at.y + (1 - p) * 16})`} opacity={p * (down ? 0.72 : 1)}>
      {busy && <rect x={-bw / 2 - 6 - pulse * 4} y={-bh / 2 - 6 - pulse * 4} width={bw + 12 + pulse * 8} height={bh + 12 + pulse * 8} rx={16} fill="none" stroke={th.highlight} strokeWidth={3} opacity={0.35 + 0.3 * pulse} />}
      <rect x={-bw / 2} y={-bh / 2} width={bw} height={bh} rx={12} fill={active ? th.accentSoft : th.surface} stroke={down || busy ? col : active ? th.accent : th.text} strokeWidth={active || busy ? 4 : 2.5} strokeDasharray={down ? "10 8" : undefined} />
      {n.count != null && (
        <g transform={`translate(${bw / 2 - 34} ${-bh / 2 + 6})`}>
          <rect x={-8} y={0} width={56} height={44} rx={10} fill={th.bg} stroke={busy ? th.highlight : th.accent} strokeWidth={2.5} />
          <text x={20} y={23} textAnchor="middle" dominantBaseline="central" fill={th.text} fontSize={28} fontWeight={700} fontFamily={MONO}>{n.count}</text>
        </g>
      )}
      {down && (
        <g transform={`translate(${-bw / 2 + 16} ${-bh / 2 + 14})`}>
          <circle cx={20} cy={20} r={20} fill={th.highlight} />
          <path d="M12 12 L28 28 M28 12 L12 28" stroke={th.bg} strokeWidth={5} strokeLinecap="round" />
        </g>
      )}
      {icon && (
        <svg x={short && !narrow ? -bw / 2 + 36 : -isz / 2} y={short && !narrow ? -isz / 2 : -bh / 2 + 16} width={isz} height={(isz * icon.h) / icon.w} viewBox={`0 0 ${icon.w} ${icon.h}`}
          style={{color: col, overflow: "visible"}}><g dangerouslySetInnerHTML={{__html: icon.body}} /></svg>
      )}
      {lines.map((ln, k) => (
        <text key={k} x={lx} y={ly0 + (k - (lines.length - 1) / 2) * fs * 1.12} textAnchor="middle" dominantBaseline="central" fill={th.text} fontSize={fs} fontWeight={600} fontFamily={FONT} letterSpacing={-0.8}>{ln}</text>
      ))}
    </g>
  );
};

const EdgeView: React.FC<{n: number; e: Edge; pos: P[]; bw: number; bh: number; short: boolean; flow: boolean; t: number; lane: number; tight?: boolean; layered?: boolean}> = ({n, e, pos, bw, bh, short, flow, t, lane, tight, layered}) => {
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
  const count = e.n ?? 1, dropped = !!e.drop;   // a flow always sends one packet; a diagram sends them only when the script says so (x4, or ! for a drop)
  const sends = flow || count > 1 || dropped;
  const lab = e.label ? e.label.length * (short ? 17 : 16) + 70 : 0;
  return (
    <g>
      <line x1={x1} y1={y1} x2={px} y2={py} stroke={e.drop ? th.highlight : th.accent} strokeWidth={4} strokeLinecap="round" strokeDasharray={e.drop ? "10 9" : e.from > e.to ? "3 12" : undefined}
        markerEnd={grow > 0.98 ? "url(#ah)" : undefined} />
      {grow > 0.55 && (
        <g transform={`translate(${layered ? mx + (dx < 0 ? -(lab / 2 + 14) : lab / 2 + 14) : mx} ${layered ? my : my + (short ? 0 : tight ? (lane && e.from < e.to ? bh / 2 + 40 : -(bh / 2 + 40)) : lane ? (e.from < e.to ? 50 : -50) : -38)})`} opacity={Math.min(1, (grow - 0.55) * 2.2)}>
          <rect x={-lab / 2} y={-26} width={lab || 52} height={52} rx={26} fill={th.bg} stroke={th.rule} strokeWidth={2} />
          <circle cx={lab ? -lab / 2 + 26 : 0} cy={0} r={15} fill={th.accent} />
          <text x={lab ? -lab / 2 + 26 : 0} y={1} textAnchor="middle" dominantBaseline="central" fill={th.bg} fontSize={19} fontWeight={700} fontFamily={MONO}>{n}</text>
          {e.label && <text x={14} y={1} textAnchor="middle" dominantBaseline="central" fill={th.text} fontSize={short ? 27 : 26} fontFamily={MONO}>{e.label}</text>}
        </g>
      )}
      {sends && Array.from({length: count}).map((_, k) => {
        const t0 = e.t + 0.5 + k * 0.3, reach = dropped ? 0.86 : 1;
        const pk = interpolate(t, [t0, t0 + 1.2], [0, reach], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
        const fall = dropped ? interpolate(t, [t0 + 1.2, t0 + 1.9], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}) : 0;
        if (t < t0 || (!dropped && pk >= 1 && k < count - 1 && t > t0 + 1.4) || fall >= 1) return null;
        const cx = x1 + (x2 - x1) * pk, cy = y1 + (y2 - y1) * pk + fall * 90;
        return (
          <g key={k} transform={`translate(${cx} ${cy}) rotate(${fall * 40})`} opacity={1 - fall}>
            <rect x={-13} y={-13} width={26} height={26} rx={6} fill={dropped && fall > 0 ? th.highlight : th.accent} />
            {dropped && fall > 0 && <path d="M-7 -7 L7 7 M7 -7 L-7 7" stroke={th.bg} strokeWidth={4} strokeLinecap="round" />}
          </g>
        );
      })}
    </g>
  );
};

/** A walk through an array: big cells that fill the width (a long array wraps into two rows on a Short), the step's note and its counters as
 *  big tiles ("count = 2" -> a COUNT tile reading 2), all centred in the frame so nothing is a thin strip at the top. */
const Trace: React.FC<{s: Scene; short: boolean}> = ({s, short}) => {
  const th = useTheme(), {t} = useT();
  const cells = s.cells ?? [], steps = s.steps ?? [];
  const cur: Step | undefined = [...steps].reverse().find((st) => st.t <= t);
  const n = Math.max(1, cells.length);
  const perRow = short && n > 6 ? Math.ceil(n / 2) : n;
  const rows = Array.from({length: Math.ceil(n / perRow)}, (_, r) => cells.slice(r * perRow, r * perRow + perRow).map((c, k) => ({c, i: r * perRow + k})));
  const gap = short ? 18 : 16;
  const cw = Math.floor(Math.min(short ? 190 : 170, ((short ? 888 : 1620) - gap * (perRow - 1)) / perRow));
  const p = useProgress(0.4, 1.0);
  const since = cur ? t - cur.t : 0;
  const pop = interpolate(since, [0, 0.3], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const look = (i: number) => cur?.found.includes(i) ? {border: th.positive, fill: `${th.positive}33`, op: 1}
    : cur?.active.includes(i) ? {border: th.accent, fill: th.accentSoft, op: 1}
    : cur?.out.includes(i) ? {border: th.rule, fill: "transparent", op: 0.35} : {border: th.text, fill: th.surface, op: 1};
  const tiles = (cur?.memo ?? []).map((m) => {
    const k = m.match(/^\s*([^=:]{1,24}?)\s*[=:]\s*(.{1,14})$/);
    return k ? {name: k[1], value: k[2]} : {name: "", value: m};
  });
  return (
    <>
      <Heading text={s.title} short={short} />
      <div style={{flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: short ? 56 : 30}}>
        <div style={{display: "flex", flexDirection: "column", gap: short ? 26 : 12, alignItems: "center", opacity: p}}>
          {rows.map((row, r) => (
            <div key={r} style={{display: "flex", gap}}>
              {row.map(({c, i}) => {
                const l = look(i), lit = l.border !== th.text && l.op === 1;
                return (
                  <div key={i} style={{width: cw, opacity: l.op}}>
                    <div style={{height: cw, border: `${lit ? 6 : 3}px solid ${l.border}`, borderRadius: Math.round(cw * 0.12), background: l.fill, display: "flex",
                      alignItems: "center", justifyContent: "center", fontSize: Math.round(cw * (String(c).length > 3 ? 0.3 : 0.46)), fontWeight: 700, fontFamily: MONO,
                      transform: lit ? `scale(${0.94 + 0.06 * pop})` : undefined}}>{c}</div>
                    <div style={{textAlign: "center", color: th.muted, fontSize: short ? 28 : 24, fontFamily: MONO, marginTop: 8}}>{i}</div>
                    <div style={{textAlign: "center", color: th.accent, fontWeight: 700, fontSize: short ? 32 : 28, fontFamily: MONO, minHeight: short ? 40 : 34}}>
                      {(cur?.pointers ?? []).filter((q) => q.at === i).map((q) => <div key={q.name}>▲ {q.name}</div>)}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        {cur?.note && <div style={{textAlign: "center", fontSize: short ? 66 : 44, fontWeight: 700, letterSpacing: -1, lineHeight: 1.15, opacity: pop}}>{cur.note}</div>}
        {tiles.length > 0 && (
          <div style={{display: "flex", gap: short ? 24 : 20, justifyContent: "center", flexWrap: "wrap"}}>
            {tiles.map((m, k) => (
              <div key={k} style={{minWidth: short ? 230 : 190, padding: short ? "18px 28px" : "12px 22px", borderRadius: 18, border: `3px solid ${th.rule}`,
                background: th.surface, textAlign: "center"}}>
                {m.name && <div style={{fontSize: short ? 30 : 24, color: th.muted, fontFamily: MONO, textTransform: "uppercase", letterSpacing: 1.5}}>{m.name}</div>}
                <div style={{fontSize: m.name ? (short ? 76 : 56) : (short ? 40 : 32), fontWeight: 700, fontFamily: MONO, color: th.text}}>{m.value}</div>
              </div>
            ))}
          </div>
        )}
      </div>
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
