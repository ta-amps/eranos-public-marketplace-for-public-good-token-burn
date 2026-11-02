import { useState } from "react";

import type { VideoNoun } from "../lib/nouns";
import { useNoun } from "../lib/useNoun";
import { AppLink } from "../router";

/** A recorded preview, rendered from the same instruction-noun export as the other pages. */
export function Video() {
  const { value: page, failed: nounFailed } = useNoun<VideoNoun>("video");
  const [failed, setFailed] = useState(false);
  if (nounFailed) throw new Error("Video page text could not be loaded");
  if (!page) return null;

  return (
    <article className="er-video" data-testid="video-page">
      <header className="er-video-header">
        <p className="er-trust-kicker">{page.kicker}</p>
        <h1>{page.title}</h1>
        <p className="er-lede">{page.intro}</p>
      </header>
      <figure className="er-video-player">
        <video controls playsInline preload="none" poster={page.poster} aria-label={page.player_label} aria-describedby="video-context" onError={() => setFailed(true)}>
          <source src={page.media} type="video/mp4" onError={() => setFailed(true)} />
          <track kind="captions" src={page.captions} srcLang="en" label={page.captions_label} default />
          <a href={page.media}>{page.download}</a>
        </video>
        <figcaption id="video-context">{page.context}</figcaption>
      </figure>
      {failed && <p role="alert">{page.playback_error}</p>}
      <div className="er-video-actions">
        {page.actions.map((action, index) => (
          <AppLink key={action.to} to={action.to} className={index === 0 ? "er-btn-primary" : "er-btn-secondary"}>
            {action.label}
          </AppLink>
        ))}
      </div>
      <p className="er-small"><a href={page.media} download>{page.download}</a> · <a href={page.captions}>{page.captions_download}</a></p>
      <details className="er-video-transcript">
        <summary>{page.transcript_label}</summary>
        {page.transcript.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
      </details>
    </article>
  );
}
