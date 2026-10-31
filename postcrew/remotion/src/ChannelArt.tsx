import React from "react";
import {AbsoluteFill} from "remotion";
import {FONT, ThemeContext, keyWord} from "./theme";
import {useFonts} from "./fonts";
import type {Theme} from "./types";

export type ChannelArtProps = {name: string; tagline: string; topics: string[]; theme: Theme; guides?: boolean};

// YouTube channel art is 2560 x 1440. A phone shows only the centre 1546 x 423; a desktop browser 2560 x 423; a TV all of it.
const W = 2560, H = 1440, SAFE_W = 1546, BAND_H = 423, X0 = (W - SAFE_W) / 2, Y0 = (H - BAND_H) / 2;

/** Quiet diagram fragments in the wide area (only desktop and TV show it): boxes joined by arrows, in the colours of the page. */
const Motif: React.FC<{side: "left" | "right"}> = ({side}) => {
  const th = React.useContext(ThemeContext);
  const flip = side === "right" ? 1 : -1, x = side === "right" ? W - 430 : 430;   // fragments start at the edge of the safe area's neighbours
  const box = (cx: number, cy: number, w: number, on = false) => (
    <rect key={`${cx}-${cy}`} x={cx - w / 2} y={cy - 36} width={w} height={72} rx={12} fill="none" stroke={on ? th.accent : th.rule} strokeWidth={on ? 4 : 3} />
  );
  const line = (x1: number, y1: number, x2: number, y2: number, on = false) => (
    <line key={`${x1}${y1}${x2}${y2}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={on ? th.accent : th.rule} strokeWidth={on ? 4 : 3} strokeLinecap="round" strokeDasharray={on ? undefined : "2 14"} />
  );
  return (
    <g opacity={0.9}>
      {box(x + flip * 150, Y0 + 62, 220, true)}
      {box(x + flip * 150, Y0 + 211, 220)}
      {box(x + flip * 150, Y0 + 360, 220)}
      {box(x + flip * 470, Y0 + 136, 200)}
      {box(x + flip * 470, Y0 + 286, 200)}
      {line(x + flip * 150, Y0 + 98, x + flip * 150, Y0 + 175, true)}
      {line(x + flip * 150, Y0 + 247, x + flip * 150, Y0 + 324)}
      {line(x + flip * 260, Y0 + 80, x + flip * 370, Y0 + 124, true)}
      {line(x + flip * 260, Y0 + 230, x + flip * 370, Y0 + 274)}
      {line(x + flip * 470, Y0 + 172, x + flip * 470, Y0 + 250)}
    </g>
  );
};

/** The channel cover: the name, one line on what the channel is, the topics. Everything that matters sits inside the phone-safe centre. */
export const ChannelArt: React.FC<ChannelArtProps> = ({name, tagline, topics, theme, guides}) => {
  useFonts();
  const words = name.split(/\s+/).filter(Boolean), key = keyWord(words);
  return (
    <ThemeContext.Provider value={theme}>
      <AbsoluteFill style={{background: theme.bg, fontFamily: FONT}}>
        <svg width={W} height={H} style={{position: "absolute", inset: 0}}><Motif side="left" /><Motif side="right" /></svg>
        <div style={{position: "absolute", left: X0, top: Y0, width: SAFE_W, height: BAND_H, display: "flex", flexDirection: "column", justifyContent: "center"}}>
          <div style={{width: 120, height: 10, background: theme.accent, marginBottom: 22}} />
          <div style={{fontSize: 156, fontWeight: 700, lineHeight: 1, letterSpacing: -5, color: theme.text}}>
            {words.map((w, i) => <span key={i} style={{display: "inline-block", marginRight: "0.24em", color: i === key ? theme.highlight : theme.text}}>{w}</span>)}
          </div>
          <div style={{fontSize: 44, fontWeight: 600, color: theme.muted, marginTop: 16, letterSpacing: -0.5}}>{tagline}</div>
          <div style={{display: "flex", gap: 14, marginTop: 24}}>
            {topics.map((t) => (
              <div key={t} style={{display: "flex", alignItems: "center", gap: 12, border: `3px solid ${theme.rule}`, borderRadius: 999, padding: "9px 24px 9px 18px", fontSize: 30, fontWeight: 600, color: theme.text}}>
                <span style={{width: 12, height: 12, borderRadius: 6, background: theme.accent}} />{t}
              </div>
            ))}
          </div>
        </div>
        {guides && (
          <svg width={W} height={H} style={{position: "absolute", inset: 0}}>
            <rect x={X0} y={Y0} width={SAFE_W} height={BAND_H} fill="none" stroke="#ff3b6b" strokeWidth={4} strokeDasharray="14 10" />
            <rect x={0} y={Y0} width={W} height={BAND_H} fill="none" stroke="#2bd4a0" strokeWidth={4} strokeDasharray="14 10" />
            <text x={X0 + 10} y={Y0 - 14} fill="#ff3b6b" fontSize={30} fontFamily={FONT}>phone-safe 1546 x 423</text>
            <text x={20} y={Y0 + BAND_H + 40} fill="#2bd4a0" fontSize={30} fontFamily={FONT}>desktop 2560 x 423 (TV shows all)</text>
          </svg>
        )}
      </AbsoluteFill>
    </ThemeContext.Provider>
  );
};
