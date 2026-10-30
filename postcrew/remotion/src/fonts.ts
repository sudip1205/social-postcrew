import {continueRender, delayRender, staticFile} from "remotion";
import {useEffect, useState} from "react";

const FACES: [string, string, number][] = [
  ["Inter", "Inter-Regular.ttf", 400], ["Inter", "Inter-SemiBold.ttf", 600], ["Inter", "Inter-Bold.ttf", 700],
  ["JetBrains Mono", "JetBrainsMono-Regular.ttf", 400], ["JetBrains Mono", "JetBrainsMono-Bold.ttf", 700],
];

/** Loads the fonts once; a frame is not drawn before they are ready. */
export const useFonts = () => {
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    Promise.all(FACES.map(([family, file, weight]) =>
      new FontFace(family, `url(${staticFile(file)})`, {weight: String(weight)}).load().then((f) => document.fonts.add(f))))
      .catch(() => undefined)
      .finally(() => continueRender(handle));
  }, [handle]);
};
