import React from "react";
import {AbsoluteFill} from "remotion";
import {FONT, MONO, ThemeContext, keyWord, useTheme} from "./theme";
import {useFonts} from "./fonts";
import type {Illustration, ThumbProps} from "./types";

const KEYWORDS = /\b(def|return|if|else|elif|for|while|in|not|and|or|import|from|class|const|let|var|function|new|true|false|True|False|None|null|async|await|break|continue|try|except|raise)\b/g;

/** The picture on the right of the thumbnail: the video's own diagram, array or code, drawn big and simple. */
const Picture: React.FC<{p: Illustration}> = ({p}) => {
  const th = useTheme();
  if (p.kind === "diagram") {
    const bh = 100, gap = 78, w = 400, h = p.nodes.length * bh + (p.nodes.length - 1) * gap;
    return (
      <svg width={w} height={h} style={{overflow: "visible"}}>
        <defs><marker id="ta" markerUnits="userSpaceOnUse" markerWidth="26" markerHeight="26" refX="20" refY="13" orient="auto"><path d="M0,0 L26,13 L0,26 z" fill={th.accent} /></marker></defs>
        {p.nodes.map((n, i) => {
          const y = i * (bh + gap), on = i === p.focus;
          return (
            <g key={i}>
              {i > 0 && <line x1={w / 2} y1={y - gap + 6} x2={w / 2} y2={y - 8} stroke={th.accent} strokeWidth={7} strokeLinecap="round" markerEnd="url(#ta)" />}
              <rect x={on ? 0 : 20} y={y} width={on ? w : w - 40} height={bh} rx={16} fill={on ? th.accentSoft : th.surface} stroke={on ? th.highlight : th.text} strokeWidth={on ? 8 : 4} />
              <text x={w / 2} y={y + bh / 2 + 1} textAnchor="middle" dominantBaseline="central" fill={on ? th.highlight : th.text} fontSize={on ? 38 : 32} fontWeight={700} fontFamily={FONT}>{n}</text>
            </g>
          );
        })}
      </svg>
    );
  }
  if (p.kind === "trace") {
    const size = 112;
    return (
      <div style={{display: "grid", gridTemplateColumns: `repeat(3, ${size}px)`, gap: 18}}>
        {p.cells.map((c, i) => {
          const on = p.found.includes(i);
          return (
            <div key={i} style={{height: size, border: `${on ? 8 : 4}px solid ${on ? th.highlight : th.text}`, borderRadius: 16, background: on ? th.accentSoft : th.surface, color: on ? th.highlight : th.text,
              display: "flex", alignItems: "center", justifyContent: "center", fontSize: 52, fontWeight: 700, fontFamily: MONO}}>{c}</div>
          );
        })}
      </div>
    );
  }
  return (
    <div style={{width: 470, background: th.surface, border: `4px solid ${th.text}`, borderRadius: 18, padding: "28px 30px", fontFamily: MONO, fontSize: 28, lineHeight: 1.55, color: th.text}}>
      {p.lines.map((l, i) => <div key={i} style={{whiteSpace: "pre"}}>{l.split(KEYWORDS).map((part, j) => (j % 2 ? <span key={j} style={{color: th.accent, fontWeight: 700}}>{part}</span> : part))}</div>)}
    </div>
  );
};

/**
 * The thumbnail: a few very large words that read at phone size with the key word in orange, a rule, the title in a quiet colour, and
 * (when the video has one) a picture of its own diagram, array or code on the right. The look of the video: white or black.
 */
export const Thumbnail: React.FC<ThumbProps> = ({text, title, theme, illustration}) => {
  useFonts();
  const words = text.split(/\s+/).filter(Boolean), key = keyWord(words);
  const pic = !!illustration;
  const size = pic ? (words.length <= 2 ? 150 : words.length === 3 ? 124 : 106) : (words.length <= 2 ? 200 : words.length === 3 ? 170 : 140);
  return (
    <ThemeContext.Provider value={theme}>
      <AbsoluteFill style={{background: theme.bg, fontFamily: FONT, padding: "0 80px", justifyContent: "center"}}>
        <div style={{width: 150, height: 14, background: theme.accent, marginBottom: 34}} />
        <div style={{fontSize: size, fontWeight: 700, lineHeight: 0.99, letterSpacing: -size * 0.035, maxWidth: pic ? 680 : 1100}}>
          {words.map((w, i) => <span key={i} style={{display: "inline-block", color: i === key ? theme.highlight : theme.text, marginRight: "0.22em"}}>{w}</span>)}
        </div>
        <div style={{color: theme.muted, fontSize: 38, fontWeight: 600, marginTop: 36, maxWidth: pic ? 680 : 1000, lineHeight: 1.25}}>{title}</div>
        {illustration && <div style={{position: "absolute", right: 80, top: 0, bottom: 16, display: "flex", alignItems: "center"}}><Picture p={illustration} /></div>}
        <div style={{position: "absolute", left: 0, right: 0, bottom: 0, height: 16, background: theme.accent}} />
      </AbsoluteFill>
    </ThemeContext.Provider>
  );
};
