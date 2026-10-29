import React from "react";
import {Composition, Still} from "remotion";
import {Video, totalFrames} from "./Video";
import {Thumbnail} from "./Thumbnail";
import type {ThumbProps, VideoProps} from "./types";

const demo: VideoProps = {
  format: "short", width: 1080, height: 1920, fps: 30,
  scenes: [{layout: "title", title: "Preview", items: [], code: "", language: "", seconds: 3, captions: []}],
};

export const Root: React.FC = () => (
  <>
    <Composition
      id="Video" component={Video} defaultProps={demo} width={1080} height={1920} fps={30} durationInFrames={90}
      calculateMetadata={({props}) => ({durationInFrames: totalFrames(props), fps: props.fps, width: props.width, height: props.height})}
    />
    <Still id="Thumbnail" component={Thumbnail} width={1280} height={720}
      defaultProps={{text: "Thumbnail text", title: "Video title"} as ThumbProps} />
  </>
);
