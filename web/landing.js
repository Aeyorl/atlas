const menuButton = document.querySelector('.menu-toggle');
const mobileMenu = document.querySelector('#mobileMenu');
const menuBackdrop = document.querySelector('[data-menu-backdrop]');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

document.documentElement.classList.add('js-ready');

const setMenuOpen = open => {
  if (!menuButton || !mobileMenu || !menuBackdrop) return;

  menuButton.setAttribute('aria-expanded', String(open));
  menuButton.setAttribute('aria-label', open ? 'Close navigation menu' : 'Open navigation menu');
  const icon = menuButton.querySelector('i');
  icon?.classList.toggle('fa-bars', !open);
  icon?.classList.toggle('fa-xmark', open);
  mobileMenu.hidden = !open;
  menuBackdrop.hidden = !open;
  document.body.classList.toggle('menu-open', open);
};

menuButton?.addEventListener('click', () => {
  setMenuOpen(menuButton.getAttribute('aria-expanded') !== 'true');
});
menuBackdrop?.addEventListener('click', () => setMenuOpen(false));
mobileMenu?.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => setMenuOpen(false));
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') setMenuOpen(false);
});
window.matchMedia('(min-width: 961px)').addEventListener('change', event => {
  if (event.matches) setMenuOpen(false);
});

const counters = [...document.querySelectorAll('[data-count]')];
const runCounter = (element, index) => {
  if (element.dataset.counted) return;
  element.dataset.counted = 'true';

  const target = Number(element.dataset.count);
  if (reducedMotion || !Number.isFinite(target)) {
    element.textContent = String(target);
    return;
  }

  const duration = 1500 + index * 80;
  const delay = 480 + index * 90;
  const startedAt = performance.now() + delay;
  const step = now => {
    if (now < startedAt) {
      requestAnimationFrame(step);
      return;
    }
    const progress = Math.min((now - startedAt) / duration, 1);
    const eased = 1 - (1 - progress) ** 3;
    element.textContent = String(Math.round(target * eased));
    if (progress < 1) requestAnimationFrame(step);
  };

  requestAnimationFrame(step);
};

if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const index = counters.indexOf(entry.target);
      runCounter(entry.target, index);
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.25 });
  counters.forEach(counter => observer.observe(counter));
} else {
  counters.forEach(runCounter);
}

const sectionLinks = [...document.querySelectorAll('.desktop-nav a[href^="#"], .mobile-menu a[href^="#"]')];
const sections = [...document.querySelectorAll('#top, #network, #protocol, #architecture, #deployment, #developers, #security')];
const markActiveSection = id => {
  sectionLinks.forEach(link => {
    const active = link.hash === `#${id}`;
    link.classList.toggle('is-active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
};

if ('IntersectionObserver' in window && sections.length) {
  const sectionObserver = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (visible) markActiveSection(visible.target.id);
  }, { rootMargin: '-20% 0px -65% 0px', threshold: [0, 0.1, 0.3, 0.6] });
  sections.forEach(section => sectionObserver.observe(section));
}

const copyButton = document.querySelector('#copyCode');
const copyTokenCa = document.querySelector('#copyTokenCa');
copyTokenCa?.addEventListener('click', async () => {
  if (!navigator.clipboard) return;
  try {
    await navigator.clipboard.writeText(copyTokenCa.dataset.address);
    copyTokenCa.textContent = 'Copied';
    window.setTimeout(() => { copyTokenCa.textContent = 'Copy'; }, 1600);
  } catch {
    copyTokenCa.textContent = 'Unavailable';
    window.setTimeout(() => { copyTokenCa.textContent = 'Copy'; }, 2000);
  }
});
const quickstartCode = document.querySelector('#quickstartCode');
copyButton?.addEventListener('click', async () => {
  if (!quickstartCode || !navigator.clipboard) return;
  const originalText = copyButton.textContent;
  try {
    await navigator.clipboard.writeText(quickstartCode.textContent.trim());
    copyButton.textContent = 'Copied';
    window.setTimeout(() => { copyButton.textContent = originalText; }, 1600);
  } catch {
    copyButton.textContent = 'Copy unavailable';
    window.setTimeout(() => { copyButton.textContent = originalText; }, 2000);
  }
});
