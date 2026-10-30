import React from "react";
import {Easing, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import type {Theme} from "./types";

/** Preview colours (npm run studio); a real render always brings its own theme in the props. */
export const PAPER: Theme = {
  name: "paper", bg: "#F5F2EB", surface: "#FBFAF6", text: "#424242", muted: "#6F6B62", rule: "#D8D2C4",
  accent: "#279CF5", accentSoft: "rgba(39, 156, 245, 0.12)", highlight: "#FA7900", positive: "#068200",
};
export const FONT = "Inter, 'Helvetica Neue', Arial, sans-serif";
export const MONO = "'JetBrains Mono', Menlo, Consolas, monospace";

export const ThemeContext = React.createContext<Theme>(PAPER);
export const useTheme = () => React.useContext(ThemeContext);

/** The word that carries the idea: the longest one (the last, when tied). Shown in the highlight colour (orange). */
export const keyWord = (words: string[]) =>
  words.length ? words.reduce((best, w, i) => (w.replace(/\W/g, "").length >= words[best].replace(/\W/g, "").length ? i : best), 0) : -1;

/** The one easing every move uses: it starts fast and settles slowly. No bounce, no overshoot. */
export const ease = Easing.bezier(0.16, 1, 0.3, 1);

/** Time in the current scene, in seconds. */
export const useT = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  return {t: f / fps, f, fps};
};

/** 0 to 1, starting at second `at`, taking `dur` seconds, eased. */
export const useProgress = (at: number, dur = 0.9) => {
  const {t} = useT();
  return interpolate(t, [at, at + dur], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
};
