import type { Video, VideosCard } from "./contract";
import { External } from "./External";

function VideoTile({ video }: { video: Video }) {
  const meta = [video.views, video.published].filter(Boolean);

  return (
    // Opens in the YouTube app when it's installed, the browser otherwise
    <External href={video.url} className="video" title={video.title}>
      <span className="video-thumb">
        <img src={video.thumbnail} alt="" loading="lazy" draggable={false} />
        {video.live ? (
          <span className="video-badge video-live">Live</span>
        ) : (
          video.duration && <span className="video-badge">{video.duration}</span>
        )}
      </span>
      <span className="video-body">
        <span className="video-title">{video.title}</span>
        {video.channel && <span className="video-meta">{video.channel}</span>}
        {meta.length > 0 && <span className="video-meta">{meta.join(" · ")}</span>}
      </span>
    </External>
  );
}

export function VideosCardView({ card }: { card: VideosCard }) {
  // Only web links open; anything else in a card is dropped rather than handed to the system opener
  const videos = card.videos.filter((video) => /^https:\/\//i.test(video.url));
  if (videos.length === 0) return null;
  const count = `${videos.length} ${videos.length === 1 ? "video" : "videos"}`;

  return (
    <section className="videos-card" aria-label={`Videos for ${card.query}`}>
      <header className="places-header">
        <span>{count}</span>
        <span className="places-query">{card.query}</span>
      </header>
      <div className="places-strip">
        {videos.map((video) => (
          <VideoTile key={video.id} video={video} />
        ))}
      </div>
    </section>
  );
}
