const header = document.querySelector('[data-header]');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const updateHeader = () => header.classList.toggle('scrolled', window.scrollY > 24);
updateHeader();
window.addEventListener('scroll', updateHeader, { passive: true });

// The intro video plays muted on a loop, unless the visitor asked for less motion.
const video = document.querySelector('[data-intro-video]');
const toggle = document.querySelector('[data-video-toggle]');
if (video && toggle) {
  const sync = () => {
    const playing = !video.paused;
    toggle.classList.toggle('playing', playing);
    toggle.setAttribute('aria-label', playing ? 'Pause video' : 'Play video');
  };
  video.addEventListener('play', sync);
  video.addEventListener('pause', sync);
  toggle.addEventListener('click', () => (video.paused ? video.play() : video.pause()));
  toggle.hidden = false;
  sync();
  if (!reducedMotion) video.play().catch(sync);
}

if (reducedMotion) {
  document.querySelectorAll('.reveal').forEach((element) => element.classList.add('visible'));
} else {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));
}
