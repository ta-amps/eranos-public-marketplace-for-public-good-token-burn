import type { VideoNoun } from "../lib/nouns";
import { useNoun } from "../lib/useNoun";
import { AppLink } from "../router";

export function Video() {
  const video = useNoun<VideoNoun>("video").value;
  if (!video) return null;

  return (
    <article className="er-video-page" data-testid="video-page">
      <header className="er-video-header">
        <p className="er-landing-pill">{video.eyebrow}</p>
        <h1>{video.heading}</h1>
        <p className="er-lede">{video.lead}</p>
        <ul className="er-video-meta">
          {video.meta.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <div className="er-video-actions">
          {video.actions.map((action) => (
            <AppLink
              key={action.label}
              to={action.to}
              className={action.primary ? "er-btn-primary" : "er-btn-secondary"}
            >
              {action.label}
            </AppLink>
          ))}
        </div>
      </header>

      <section className="er-card er-video-player-card" aria-labelledby="video-player-title">
        <div className="er-video-player-head">
          <h2 id="video-player-title">{video.player.heading}</h2>
          <a href={video.player.mp4} download className="er-btn-secondary">
            {video.player.download_label}
          </a>
        </div>
        <figure className="er-video-figure">
          <video
            className="er-video-element"
            controls
            preload="none"
            playsInline
            poster={video.player.poster}
          >
            <source src={video.player.mp4} type="video/mp4" />
            <track
              kind="captions"
              src={video.player.vtt}
              srcLang="en"
              label={video.player.captions_label}
              default
            />
          </video>
          <figcaption className="er-small">{video.player.caption}</figcaption>
        </figure>
      </section>

      <section className="er-card er-video-section" aria-labelledby="video-transcript-title">
        <h2 id="video-transcript-title">{video.transcript.heading}</h2>
        <p className="er-muted">{video.transcript.intro}</p>
        <ol className="er-video-transcript">
          {video.transcript.items.map((item) => (
            <li key={item.time} className="er-video-transcript-row">
              <div className="er-video-transcript-meta">
                <code>{item.time}</code>
                <span>{item.scene}</span>
              </div>
              <p>{item.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="er-card er-video-section" aria-labelledby="video-evidence-title">
        <h2 id="video-evidence-title">{video.evidence.heading}</h2>
        <p className="er-muted">{video.evidence.intro}</p>
        <ul className="er-video-evidence">
          {video.evidence.items.map((item) => (
            <li key={item.label} className="er-video-evidence-row">
              {item.to ? (
                <AppLink to={item.to} className="er-text-link">
                  {item.label}
                </AppLink>
              ) : (
                <a href={item.href} className="er-text-link">
                  {item.label}
                </a>
              )}
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
      </section>

      <footer className="er-video-foot">
        <div className="er-video-actions">
          {video.next_actions.map((action) =>
            action.to ? (
              <AppLink
                key={action.label}
                to={action.to}
                className={action.primary ? "er-btn-primary" : "er-btn-secondary"}
              >
                {action.label}
              </AppLink>
            ) : (
              <a
                key={action.label}
                href={action.href}
                className={action.primary ? "er-btn-primary" : "er-btn-secondary"}
              >
                {action.label}
              </a>
            ),
          )}
        </div>
        <p className="er-small">{video.honesty}</p>
      </footer>
    </article>
  );
}
