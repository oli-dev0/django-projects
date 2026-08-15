(() => {
  const root = document.documentElement;
  const toggle = document.querySelector('.theme-toggle');
  const themeAwareImages = document.querySelectorAll('[data-theme-dark-src][data-theme-light-src]');
  const storageKey = 'projectsReferenceAppearance';

  const applyTheme = (theme) => {
    const isLight = theme === 'light';
    root.dataset.theme = isLight ? 'light' : 'dark';
    themeAwareImages.forEach((image) => {
      image.src = isLight ? image.dataset.themeLightSrc : image.dataset.themeDarkSrc;
    });
    if (!toggle) {
      return;
    }
    toggle.setAttribute('aria-pressed', String(isLight));
    toggle.setAttribute(
      'aria-label',
      isLight ? 'Switch to dark mode' : 'Switch to light mode',
    );
    toggle.querySelector('.theme-toggle__label').textContent = isLight
      ? 'dark'
      : 'light';
  };

  let savedTheme = null;
  try {
    savedTheme = localStorage.getItem(storageKey);
  } catch (_error) {
    // The reference page remains usable when storage is unavailable.
  }

  applyTheme(savedTheme === 'light' ? 'light' : 'dark');
  if (toggle) {
    toggle.hidden = false;
  }

  toggle?.addEventListener('click', () => {
    const nextTheme = root.dataset.theme === 'light' ? 'dark' : 'light';
    try {
      localStorage.setItem(storageKey, nextTheme);
    } catch (_error) {
      // Keep the in-page toggle usable.
    }
    applyTheme(nextTheme);
  });
})();
