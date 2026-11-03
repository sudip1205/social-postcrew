import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {FONT, MONO, ease, useT, useTheme} from "./theme";
import type {Scene, VTile} from "./types";

/*
 * The quiz Short's round: two tiles, A and B, play the same task at the same time while the voice asks which is better and counts down; then the
 * better one is marked, the other dims and the demo replays slower while the voice explains. Python (postcrew/quiz.py) decides every time and
 * number; this only draws a frame. The colours come from the look (the neon look is the default for a Short).
 */
const BAD = "#FF5C7A";
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

const useColors = () => {
  const th = useTheme();
  return {th, good: th.positive, bad: BAD, tone: (t?: string) => (t === "good" ? th.positive : t === "bad" ? BAD : th.accent)};
};

/* ---------- the tiles' pictures ---------- */
const Counter: React.FC<{k: string; v: number | string; color?: string}> = ({k, v, color}) => {
  const {th} = useColors();
  return k ? (
    <div style={{position: "absolute", top: 28, left: 0, right: 0, textAlign: "center", fontWeight: 700, fontSize: 30, color: th.muted, letterSpacing: 2}}>
      {k} <span style={{color: color ?? th.accent, fontFamily: MONO, fontSize: 40}}>{v}</span>
    </div>
  ) : null;
};
const Sub: React.FC<{text: string}> = ({text}) => <div style={{textAlign: "center", fontWeight: 600, fontSize: 30, color: useTheme().muted, marginBottom: 24}}>{text}</div>;

const TraceTile: React.FC<{tile: VTile; t: number}> = ({tile, t}) => {
  const {th, good} = useColors();
  const steps = tile.steps ?? [], cells = tile.cells ?? [];
  const k = Math.min(Math.floor(t / (tile.step_s ?? 0.3)), steps.length - 1), st = steps[Math.max(0, k)];
  const done = k === steps.length - 1 && (st?.found.length ?? 0) > 0;
  const size = cells.length <= 6 ? 110 : cells.length <= 10 ? 80 : 64;
  return (
    <div>
      <Counter k={tile.counter} v={k + 1} color={done ? good : th.accent} />
      <div style={{height: 14}} />
      <Sub text={tile.sub} />
      <div style={{display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap"}}>
        {cells.map((c, i) => {
          const found = st?.found.includes(i), on = st?.active.includes(i) || found, out = st?.out.includes(i);
          const col = found ? good : th.accent;
          return (
            <div key={i} style={{width: size, height: size * 0.9, borderRadius: size * 0.15, border: `3px solid ${on ? col : th.rule}`,
              background: on ? (found ? "rgba(61,220,151,0.16)" : th.accentSoft) : th.bg, color: out && !on ? th.rule : on ? th.text : th.muted,
              fontFamily: MONO, fontWeight: 700, fontSize: size * 0.38, display: "grid", placeItems: "center", boxShadow: on ? `0 0 20px ${col}55` : "none"}}>{c}</div>
          );
        })}
      </div>
      {st?.note ? <div style={{textAlign: "center", fontFamily: MONO, fontWeight: 700, fontSize: 34, marginTop: 26, color: st.found.length ? good : th.muted}}>{st.note}</div> : null}
    </div>
  );
};

const LinkTile: React.FC<{tile: VTile; t: number}> = ({tile, t}) => {
  const {th, tone} = useColors();
  const period = tile.period ?? 1, p = (t % period) / period, served = tile.fail ? 0 : Math.floor(t / period), col = tone(tile.tone);
  const W = 940 - 80, boxW = 230, lineL = boxW + 20, lineR = W - boxW - 20, lost = tile.fail && p > 0.62;
  return (
    <div style={{paddingTop: 18}}>
      <Counter k={tile.counter || "SERVED"} v={served} color={col} />
      <Sub text={tile.sub} />
      <div style={{position: "relative", height: 200}}>
        {[tile.src, tile.dst].map((name, s) => (
          <div key={s} style={{position: "absolute", top: 20, [s ? "right" : "left"]: 0, width: boxW, height: 130, borderRadius: 22, background: th.bg,
            border: `3px solid ${s && tile.fail ? BAD : s ? col : th.rule}`, color: th.text, fontWeight: 700, fontSize: 34, display: "grid", placeItems: "center", opacity: s && tile.fail ? 0.7 : 1}}>{name}</div>
        ))}
        <div style={{position: "absolute", top: 83, left: lineL, width: lineR - lineL, height: 4, background: th.rule}} />
        {!lost && <div style={{position: "absolute", top: 68, left: lineL + p * (lineR - lineL - 32), width: 32, height: 32, borderRadius: 16, background: col, boxShadow: `0 0 22px ${col}`}} />}
        {lost && <div style={{position: "absolute", top: 42, left: lineL + 0.62 * (lineR - lineL - 32) - 6, fontSize: 56, color: BAD, fontWeight: 700}}>✕</div>}
        <div style={{position: "absolute", top: 138, left: lineL, width: lineR - lineL, textAlign: "center", fontFamily: MONO, fontWeight: 700, fontSize: 40, color: col}}>
          {tile.fail ? "lost" : `${tile.ms} ms`}
        </div>
      </div>
    </div>
  );
};

const CurveTile: React.FC<{tile: VTile; t: number}> = ({tile, t}) => {
  const {th, tone} = useColors();
  const W = 840, H = 320, p = clamp01(t / 2.4), col = tone(tile.tone), pts = tile.points ?? [];
  const upto = Math.max(1, Math.round(p * (pts.length - 1))), shown = pts.slice(0, upto + 1);
  const xy = (q: number[]) => `${q[0] * W},${H - q[1] * H}`, end = shown[shown.length - 1] ?? [0, 0];
  return (
    <div style={{position: "relative"}}>
      <Counter k={tile.counter || "STEPS"} v={Math.round(end[1] * (tile.ymax ?? 1))} color={col} />
      <svg width={W} height={H + 20} style={{marginTop: 62}}>
        <line x1={0} y1={H} x2={W} y2={H} stroke={th.rule} strokeWidth={3} /><line x1={0} y1={0} x2={0} y2={H} stroke={th.rule} strokeWidth={3} />
        <polyline points={shown.map(xy).join(" ")} fill="none" stroke={col} strokeWidth={8} strokeLinecap="round" strokeLinejoin="round" style={{filter: `drop-shadow(0 0 10px ${col})`}} />
        <circle cx={end[0] * W} cy={H - end[1] * H} r={13} fill={th.text} />
      </svg>
      <div style={{position: "absolute", right: 24, bottom: -4, fontFamily: MONO, fontWeight: 700, fontSize: 44, color: col}}>{tile.label}</div>
      <div style={{position: "absolute", left: 0, bottom: -4, fontWeight: 600, fontSize: 24, color: th.muted}}>{tile.sub}</div>
    </div>
  );
};

const BarsTile: React.FC<{tile: VTile; t: number}> = ({tile, t}) => {
  const {th, tone} = useColors();
  const bars = tile.bars ?? [], top = Math.max(...bars.map((b) => b.frac), 0.0001);
  return (
    <div style={{paddingTop: 6}}>
      <Sub text={tile.sub} />
      <div style={{display: "flex", flexDirection: "column", gap: 22}}>
        {bars.map((b, i) => {
          const g = ease(clamp01((t - i * 0.25) / 1.4)), hot = b.frac >= top;
          return (
            <div key={i} style={{display: "flex", alignItems: "center", gap: 20}}>
              <div style={{width: 250, textAlign: "right", fontWeight: 700, fontSize: 28, lineHeight: 1.1, color: th.text}}>{b.label}</div>
              <div style={{flex: 1, height: 46, borderRadius: 12, background: th.bg, border: `2px solid ${th.rule}`, overflow: "hidden"}}>
                <div style={{width: `${b.frac * 100 * g}%`, height: "100%", background: hot ? tone(tile.tone || "") : th.accent, borderRadius: 10}} />
              </div>
              <div style={{width: 170, fontFamily: MONO, fontWeight: 700, fontSize: 30, color: th.accent}}>{Math.round(b.value * g)} {tile.unit}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Demo: React.FC<{tile: VTile; t: number}> = ({tile, t}) =>
  tile.kind === "trace" ? <TraceTile tile={tile} t={t} /> : tile.kind === "link" ? <LinkTile tile={tile} t={t} /> : tile.kind === "curve" ? <CurveTile tile={tile} t={t} /> : <BarsTile tile={tile} t={t} />;

/* ---------- the tile and the scene ---------- */
const Tile: React.FC<{label: string; win: boolean; reveal: boolean; badge: string; delay: number; children: React.ReactNode}> = ({label, win, reveal, badge, delay, children}) => {
  const {th} = useColors();
  const f = useCurrentFrame(), {fps} = useVideoConfig();
  const enter = spring({frame: f - delay, fps, config: {damping: 16, stiffness: 120}});
  const on = reveal && win, off = reveal && !win;
  return (
    <div style={{position: "relative", width: 940, height: 540, borderRadius: 34, background: th.surface, border: `3px solid ${on ? th.accent : th.rule}`,
      boxShadow: on ? `0 0 60px ${th.accent}70` : "none", opacity: (off ? 0.4 : 1) * enter, transform: `translateY(${(1 - enter) * 60}px) scale(${on ? 1.015 : 1})`}}>
      <div style={{position: "absolute", top: 22, left: 26, width: 52, height: 52, borderRadius: 14, background: on ? th.accent : th.rule, color: on ? th.bg : th.muted, fontWeight: 700, fontSize: 30, display: "grid", placeItems: "center"}}>{label}</div>
      {reveal && <div style={{position: "absolute", top: 22, right: 26, width: 52, height: 52, borderRadius: 26, background: on ? th.accent : "#3A2230", color: on ? th.bg : BAD, fontSize: 32, fontWeight: 700, display: "grid", placeItems: "center"}}>{on ? "✓" : "✕"}</div>}
      <div style={{position: "absolute", inset: 0, padding: "70px 40px 60px", display: "flex", flexDirection: "column", justifyContent: "center"}}>{children}</div>
      {on && badge && (
        <div style={{position: "absolute", bottom: 18, left: 0, right: 0, display: "flex", justifyContent: "center"}}>
          <div style={{background: th.accentSoft, border: `2px solid ${th.accent}`, color: th.accent, fontWeight: 700, fontSize: 24, letterSpacing: 1.5, padding: "6px 22px", borderRadius: 999}}>{badge}</div>
        </div>
      )}
    </div>
  );
};

export const VersusScene: React.FC<{s: Scene}> = ({s}) => {
  const th = useTheme(), {t} = useT(), v = s.versus!;
  const reveal = t >= v.reveal_at;
  const speed = Math.min(1, Math.max(0.5, v.demo_s / Math.max(0.5, s.seconds - v.reveal_at - 0.8)));   // the replay: half speed at the slowest, whole if the answer is short
  const tt = reveal ? (t - v.reveal_at) * speed : Math.max(0, t - v.start_s);
  const shown = v.count_at.filter((c) => t >= c).length, digit = !reveal && shown > 0 ? 4 - shown : null;
  const cap = clamp01((t - v.reveal_at - 0.3) / 0.6);
  const words = s.title.split(/\s+/).filter(Boolean), key = s.key ?? words.length;
  return (
    <AbsoluteFill style={{fontFamily: FONT, color: th.text, background: `radial-gradient(ellipse 80% 40% at 50% 38%, ${th.accentSoft}, transparent 70%), ${th.bg}`}}>
      <div style={{position: "absolute", top: 90, left: 70, right: 70, display: "flex", gap: 12}}>
        {Array.from({length: v.rounds}).map((_, i) => <div key={i} style={{flex: 1, height: 8, borderRadius: 4, background: i < v.round ? th.accent : th.rule, boxShadow: i < v.round ? `0 0 14px ${th.accent}` : "none"}} />)}
      </div>
      <div style={{position: "absolute", top: 150, width: "100%", textAlign: "center", color: th.muted, fontWeight: 700, fontSize: 26, letterSpacing: 3}}>ROUND {v.round} / {v.rounds}</div>
      <div style={{position: "absolute", top: 210, left: 60, right: 60, fontWeight: 700, fontSize: 76, textAlign: "center", lineHeight: 1.1}}>
        {words.map((w, i) => <span key={i} style={{color: i >= key ? th.accent : th.text}}>{w}{i < words.length - 1 ? " " : ""}</span>)}
      </div>
      <div style={{position: "absolute", top: 420, left: 70, display: "flex", flexDirection: "column", gap: 40}}>
        <Tile label="A" win={v.winner === "A"} reveal={reveal} badge={v.badge} delay={0}><Demo tile={v.a} t={tt} /></Tile>
        <Tile label="B" win={v.winner === "B"} reveal={reveal} badge={v.badge} delay={6}><Demo tile={v.b} t={tt} /></Tile>
      </div>
      {digit !== null && (
        <div style={{position: "absolute", top: 420 + 540 + 20 - 36, left: 540 - 36, width: 72, height: 72, borderRadius: 36, background: th.bg, border: `3px solid ${th.accent}`, fontWeight: 700,
          fontSize: 40, display: "grid", placeItems: "center", boxShadow: `0 0 24px ${th.accent}80`}}>{digit}</div>
      )}
      <div style={{position: "absolute", top: 1620, width: "100%", display: "flex", justifyContent: "center"}}>
        {!reveal
          ? <div style={{background: th.surface, border: `2px solid ${th.rule}`, borderRadius: 14, fontWeight: 600, fontSize: 34, padding: "12px 30px"}}>Pick one: <span style={{color: th.accent}}>A</span> or <span style={{color: th.accent}}>B</span>?</div>
          : <div style={{width: 900, textAlign: "center", fontWeight: 600, fontSize: 40, lineHeight: 1.3, opacity: cap, transform: `translateY(${(1 - cap) * 24}px)`}}>{v.caption}</div>}
      </div>
    </AbsoluteFill>
  );
};

/** The answer key on the closing card of a quiz: one row for each round. */
export const AnswerKey: React.FC<{rows: {name: string; answer: string}[]}> = ({rows}) => {
  const th = useTheme(), {t} = useT();
  return (
    <div style={{width: "100%"}}>
      <div style={{textAlign: "center", fontWeight: 700, fontSize: 26, letterSpacing: 3, color: th.muted}}>ANSWER KEY</div>
      <div style={{textAlign: "center", fontWeight: 700, fontSize: 84, lineHeight: 1.1, margin: "10px 0 30px"}}>How many<br /><span style={{color: th.accent}}>did you get?</span></div>
      {rows.map((r, i) => {
        const o = interpolate(t, [0.4 + i * 0.25, 0.9 + i * 0.25], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
        return (
          <div key={i} style={{display: "flex", alignItems: "center", gap: 26, padding: "20px 0", borderBottom: `2px solid ${th.rule}`, opacity: o, transform: `translateX(${(1 - o) * 40}px)`}}>
            <div style={{fontFamily: MONO, fontWeight: 700, fontSize: 32, color: th.accent}}>{String(i + 1).padStart(2, "0")}</div>
            <div style={{flex: 1}}><div style={{fontWeight: 700, fontSize: 38}}>{r.name}</div><div style={{fontWeight: 600, fontSize: 29, color: th.muted, marginTop: 2}}>{r.answer}</div></div>
            <div style={{color: th.accent, fontSize: 38, fontWeight: 700}}>✓</div>
          </div>
        );
      })}
    </div>
  );
};
