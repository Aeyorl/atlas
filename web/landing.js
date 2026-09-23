const menuButton = document.querySelector('.menu-toggle');
const menu = document.querySelector('.nav-capsule');

menuButton?.addEventListener('click', () => {
  const open = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!open));
  menu?.classList.toggle('is-open', !open);
});

menu?.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => {
    menu.classList.remove('is-open');
    menuButton?.setAttribute('aria-expanded', 'false');
  });
});

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
document.querySelectorAll('.reveal').forEach((element, index) => {
  window.setTimeout(() => element.classList.add('is-visible'), reducedMotion ? 0 : 120 + index * 140);
});

const copyButton = document.getElementById('copyCode');
copyButton?.addEventListener('click', async () => {
  const code = document.getElementById('quickstartCode')?.textContent ?? '';
  try {
    await navigator.clipboard.writeText(code);
    copyButton.textContent = 'Copied';
    window.setTimeout(() => { copyButton.textContent = 'Copy'; }, 1600);
  } catch {
    copyButton.textContent = 'Select code';
  }
});

// Ambient Animated Coordination Field with Warm Gold and Ember Radiance
const canvas = document.getElementById('agentField');
const context = canvas?.getContext('2d');

if (canvas && context) {
  const points = [];
  const rings = [96, 170, 245];

  for (let ring = 0; ring < rings.length; ring += 1) {
    const count = 38 + ring * 22;
    for (let index = 0; index < count; index += 1) {
      points.push({
        angle: (Math.PI * 2 * index) / count + ring * 0.32,
        radius: rings[ring] + Math.sin(index * 2.1) * 12,
        size: ring === 0 ? 2.2 : 1.6,
        speed: (ring % 2 ? -1 : 1) * (0.00008 + ring * 0.000025),
        alpha: 0.35 + ((index * 17) % 50) / 100,
        isGold: index % 2 === 0,
      });
    }
  }

  const draw = (time = 0) => {
    const scale = window.devicePixelRatio || 1;
    const size = canvas.clientWidth || 720;

    if (canvas.width !== Math.round(size * scale)) {
      canvas.width = Math.round(size * scale);
      canvas.height = Math.round(size * scale);
    }

    context.setTransform(scale, 0, 0, scale, 0, 0);
    context.clearRect(0, 0, size, size);

    const factor = size / 720;
    const center = size / 2;

    // Ambient Radial Core Flare (Gold to Ember Orange)
    const glow = context.createRadialGradient(center, center, 0, center, center, size * 0.44);
    glow.addColorStop(0, 'rgba(255, 210, 0, 0.28)');
    glow.addColorStop(0.35, 'rgba(255, 140, 0, 0.12)');
    glow.addColorStop(0.7, 'rgba(255, 55, 0, 0.04)');
    glow.addColorStop(1, 'rgba(5, 5, 8, 0)');
    context.fillStyle = glow;
    context.fillRect(0, 0, size, size);

    // Orbiting Agent Nodes
    points.forEach((point, index) => {
      const phase = reducedMotion ? 0 : time * point.speed;
      const x = center + Math.cos(point.angle + phase) * point.radius * factor;
      const y = center + Math.sin(point.angle + phase) * point.radius * factor * 0.78;

      context.beginPath();
      context.fillStyle = point.isGold
        ? `rgba(255, 215, 60, ${point.alpha})`
        : `rgba(255, 140, 40, ${point.alpha})`;
      context.arc(x, y, point.size * factor, 0, Math.PI * 2);
      context.fill();

      // Constellation Links
      if (index % 19 === 0) {
        context.strokeStyle = 'rgba(255, 185, 60, 0.16)';
        context.beginPath();
        context.moveTo(center, center);
        context.lineTo(x, y);
        context.stroke();
      }
    });

    // Central Nive Hub Pulse
    context.beginPath();
    context.fillStyle = '#ffd200';
    context.shadowColor = '#ff6a00';
    context.shadowBlur = 36;
    context.arc(center, center, 14 * factor, 0, Math.PI * 2);
    context.fill();

    context.shadowBlur = 0;
    context.fillStyle = '#080604';
    context.font = `700 ${Math.max(10, 11 * factor)}px "DM Mono", monospace`;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText('N', center, center + 0.5);

    if (!reducedMotion) {
      requestAnimationFrame(draw);
    }
  };

  draw();
}
