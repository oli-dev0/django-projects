(() => {
  const supportsDialogs =
    typeof window.HTMLDialogElement !== 'undefined' &&
    typeof window.HTMLDialogElement.prototype.showModal === 'function' &&
    typeof window.HTMLDialogElement.prototype.close === 'function';

  const initializeGallery = () => {
    const gallery = document.querySelector('[data-project-gallery]');
    if (!gallery || !supportsDialogs) {
      return;
    }

    const dialog = gallery.querySelector('[data-gallery-dialog]');
    const slidesContainer = gallery.querySelector('[data-gallery-slides]');
    const triggers = [...gallery.querySelectorAll('[data-gallery-trigger]')];
    const slides = [...gallery.querySelectorAll('[data-gallery-slide]')];
    const closeButton = gallery.querySelector('[data-gallery-close]');
    const previousButton = gallery.querySelector('[data-gallery-previous]');
    const nextButton = gallery.querySelector('[data-gallery-next]');
    const status = gallery.querySelector('[data-gallery-status]');
    const fallback = gallery.querySelector('[data-gallery-fallback]');

    if (
      !dialog ||
      !slidesContainer ||
      !triggers.length ||
      !slides.length ||
      !closeButton ||
      !previousButton ||
      !nextButton ||
      !status
    ) {
      return;
    }

    let activeIndex = 0;
    let opener = null;
    let touchStartX = null;
    let touchStartY = null;

    const setActiveSlide = (index) => {
      activeIndex = (index + slides.length) % slides.length;
      slides.forEach((slide, slideIndex) => {
        slide.hidden = slideIndex !== activeIndex;
      });
      status.textContent = `${activeIndex + 1} of ${slides.length}`;
      previousButton.hidden = slides.length < 2;
      nextButton.hidden = slides.length < 2;
    };

    const closeGallery = () => {
      if (dialog.open) {
        dialog.close();
      }
      opener?.focus();
      opener = null;
    };

    triggers.forEach((trigger) => {
      trigger.addEventListener('click', (event) => {
        if (gallery.dataset.galleryEnhanced !== 'true') {
          return;
        }
        event.preventDefault();
        opener = trigger;
        const requestedIndex = Number.parseInt(trigger.dataset.galleryIndex || '0', 10);
        setActiveSlide(Number.isFinite(requestedIndex) ? requestedIndex : 0);
        dialog.showModal();
        closeButton.focus();
      });
    });

    closeButton.addEventListener('click', closeGallery);
    previousButton.addEventListener('click', () => setActiveSlide(activeIndex - 1));
    nextButton.addEventListener('click', () => setActiveSlide(activeIndex + 1));
    slidesContainer.addEventListener('touchstart', (event) => {
      if (event.touches.length !== 1) {
        touchStartX = null;
        touchStartY = null;
        return;
      }
      touchStartX = event.touches[0].clientX;
      touchStartY = event.touches[0].clientY;
    }, { passive: true });
    slidesContainer.addEventListener('touchend', (event) => {
      if (touchStartX === null || touchStartY === null) {
        return;
      }
      const touch = event.changedTouches[0];
      const deltaX = touch.clientX - touchStartX;
      const deltaY = touch.clientY - touchStartY;
      touchStartX = null;
      touchStartY = null;
      if (Math.abs(deltaX) < 40 || Math.abs(deltaX) <= Math.abs(deltaY)) {
        return;
      }
      setActiveSlide(activeIndex + (deltaX < 0 ? 1 : -1));
    }, { passive: true });
    slidesContainer.addEventListener('touchcancel', () => {
      touchStartX = null;
      touchStartY = null;
    }, { passive: true });
    dialog.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        setActiveSlide(activeIndex - 1);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        setActiveSlide(activeIndex + 1);
      }
    });
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      closeGallery();
    });
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) {
        closeGallery();
      }
    });

    setActiveSlide(0);
    if (fallback) {
      fallback.open = false;
    }
    gallery.dataset.galleryEnhanced = 'true';
  };

  const initializeFeatureDialog = () => {
    const details = document.querySelector('[data-feature-details]');
    if (!details || !supportsDialogs) {
      return;
    }

    const dialog = document.querySelector('[data-feature-dialog]');
    const content = details.querySelector('[data-feature-content]');
    const dialogContent = dialog?.querySelector('[data-feature-dialog-content]');
    const summary = details.querySelector('summary');
    const closeButton = dialog?.querySelector('[data-feature-close]');

    if (!dialog || !content || !dialogContent || !summary || !closeButton) {
      return;
    }

    let opener = null;
    dialogContent.append(content);

    summary.addEventListener('click', (event) => {
      event.preventDefault();
      opener = summary;
      dialog.showModal();
      closeButton.focus();
    });
    closeButton.addEventListener('click', () => {
      dialog.close();
      opener?.focus();
      opener = null;
    });
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      closeButton.click();
    });
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) {
        closeButton.click();
      }
    });
  };

  initializeGallery();
  initializeFeatureDialog();
})();
