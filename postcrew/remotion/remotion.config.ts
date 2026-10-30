import {Config} from "@remotion/cli/config";

// the fonts (Inter, JetBrains Mono) are the ones Postcrew ships for every renderer: scenes load them with staticFile()
Config.setPublicDir("../render/fonts");
