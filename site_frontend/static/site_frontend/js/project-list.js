(function () {
  const filterRestoreKey = "project-filter-restore";

  function setupCategoryScroller(root) {
    const scroller = root.querySelector("[data-project-category-scroll]");
    const previous = root.querySelector("[data-project-category-previous]");
    const next = root.querySelector("[data-project-category-next]");
    const selected = scroller && scroller.querySelector('[aria-current="page"]');
    const overflowTolerance = 1;
    let frame;

    if (!scroller || !previous || !next) {
      return;
    }

    function updateControls() {
      const maximumScroll = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
      previous.hidden = scroller.scrollLeft <= overflowTolerance;
      next.hidden = scroller.scrollLeft >= maximumScroll - overflowTolerance;
    }

    function scheduleUpdate() {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(updateControls);
    }

    function revealSelected() {
      if (!selected) {
        updateControls();
        return;
      }

      const edgeClearance = 44;
      const scrollerRect = scroller.getBoundingClientRect();
      const selectedRect = selected.getBoundingClientRect();
      const visibleStart = scrollerRect.left + edgeClearance;
      const visibleEnd = scrollerRect.right - edgeClearance;
      if (selectedRect.left < visibleStart) {
        scroller.scrollLeft -= visibleStart - selectedRect.left;
      } else if (selectedRect.right > visibleEnd) {
        scroller.scrollLeft += selectedRect.right - visibleEnd;
      }
      updateControls();
    }

    function scrollCategories(direction) {
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const items = Array.from(scroller.querySelectorAll("li"));
      const scrollerRect = scroller.getBoundingClientRect();
      const edgeClearance = 44;
      const visibleStart = scrollerRect.left + (previous.hidden ? 0 : edgeClearance);
      const firstVisibleIndex = items.findIndex(function (item) {
        return item.getBoundingClientRect().right > visibleStart + overflowTolerance;
      });
      const currentIndex = firstVisibleIndex === -1 ? items.length - 1 : firstVisibleIndex;
      const targetIndex = Math.max(0, Math.min(items.length - 1, currentIndex + direction));
      const targetRect = items[targetIndex].getBoundingClientRect();
      const targetStart = targetIndex === 0 ? scrollerRect.left : scrollerRect.left + edgeClearance;

      scroller.scrollBy({
        left: targetRect.left - targetStart,
        behavior: reducedMotion ? "auto" : "smooth",
      });
    }

    previous.addEventListener("click", function () {
      scrollCategories(-1);
    });
    next.addEventListener("click", function () {
      scrollCategories(1);
    });
    scroller.addEventListener("scroll", scheduleUpdate, { passive: true });

    revealSelected();
    if (window.ResizeObserver) {
      new ResizeObserver(revealSelected).observe(scroller);
    } else {
      window.addEventListener("resize", revealSelected);
    }
    if (document.fonts) {
      document.fonts.ready.then(revealSelected);
    }
  }

  function setupProjectFilters(root) {
    const form = root.querySelector("[data-project-filter-form]");
    const panel = root.querySelector("[data-project-filter-panel]");
    const toggle = root.querySelector("[data-project-filter-toggle]");
    const dropdowns = Array.from(root.querySelectorAll("[data-project-filter-dropdown]"));
    const searchForm = root.querySelector("[data-project-search-form]");
    const results = document.querySelector("[data-project-filter-results]");
    const status = results
      ? results.querySelector("[data-project-filter-status]")
      : null;

    if (!form || !panel || !toggle || !dropdowns.length) {
      return;
    }

    root.classList.add("project-filters--enhanced");
    toggle.hidden = false;
    dropdowns.forEach(function (dropdown) {
      const dropdownToggle = dropdown.querySelector("[data-project-dropdown-toggle]");
      if (dropdownToggle) {
        dropdownToggle.hidden = false;
      }
    });
    function setPanelOpen(open) {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
    }

    function setDropdownOpen(dropdown, open) {
      const dropdownToggle = dropdown.querySelector("[data-project-dropdown-toggle]");
      const dropdownPanel = dropdown.querySelector("[data-project-dropdown-panel]");
      if (!dropdownToggle || !dropdownPanel) {
        return;
      }
      dropdownPanel.hidden = !open;
      dropdownToggle.setAttribute("aria-expanded", String(open));
    }

    function closeDropdowns(except) {
      dropdowns.forEach(function (dropdown) {
        if (dropdown !== except) {
          setDropdownOpen(dropdown, false);
        }
      });
    }

    function markUpdating() {
      if (results) {
        results.setAttribute("aria-busy", "true");
      }
      if (status) {
        status.textContent = root.dataset.projectFilterUpdating || "Updating projects...";
      }
    }

    function rememberTechnologyDropdown() {
      const dropdown = dropdowns.find(function (candidate) {
        return candidate.dataset.projectFilterGroup === "technology";
      });
      const dropdownPanel = dropdown
        ? dropdown.querySelector("[data-project-dropdown-panel]")
        : null;
      const scrollableOptions = dropdown
        ? dropdown.querySelector(".project-filters__options--scroll")
        : null;
      if (!dropdownPanel) {
        return;
      }

      try {
        window.sessionStorage.setItem(filterRestoreKey, JSON.stringify({
          scope: "projects-list",
          dropdownPanelId: dropdownPanel.id,
          scrollTop: scrollableOptions ? scrollableOptions.scrollTop : 0,
        }));
      } catch {
        // Filtering must work when browser storage is unavailable.
      }
    }

    function takeRememberedDropdown() {
      let stored;
      try {
        stored = window.sessionStorage.getItem(filterRestoreKey);
        window.sessionStorage.removeItem(filterRestoreKey);
      } catch {
        return null;
      }

      if (!stored) {
        return null;
      }

      try {
        const state = JSON.parse(stored);
        if (
          state.scope !== "projects-list"
          || state.dropdownPanelId !== "project-technology-options"
        ) {
          return null;
        }
        return state;
      } catch {
        return null;
      }
    }

    function restoreDropdown(state) {
      const dropdown = dropdowns.find(function (candidate) {
        const dropdownPanel = candidate.querySelector("[data-project-dropdown-panel]");
        return dropdownPanel && dropdownPanel.id === state.dropdownPanelId;
      });
      if (!dropdown) {
        return false;
      }

      setPanelOpen(true);
      closeDropdowns(dropdown);
      setDropdownOpen(dropdown, true);

      window.requestAnimationFrame(function () {
        const scrollableOptions = dropdown.querySelector(
          ".project-filters__options--scroll",
        );
        if (scrollableOptions && Number.isFinite(state.scrollTop)) {
          scrollableOptions.scrollTop = state.scrollTop;
        }
      });
      return true;
    }

    function submitFilterForm() {
      if (form.requestSubmit) {
        form.requestSubmit();
        return;
      }
      markUpdating();
      form.submit();
    }

    toggle.addEventListener("click", function () {
      const opening = panel.hidden;
      setPanelOpen(opening);
      if (!opening) {
        closeDropdowns();
      }
    });

    dropdowns.forEach(function (dropdown) {
      const dropdownToggle = dropdown.querySelector("[data-project-dropdown-toggle]");
      const dropdownPanel = dropdown.querySelector("[data-project-dropdown-panel]");
      if (!dropdownToggle || !dropdownPanel) {
        return;
      }
      dropdownToggle.addEventListener("click", function () {
        const opening = dropdownPanel.hidden;
        closeDropdowns(dropdown);
        setDropdownOpen(dropdown, opening);
      });
    });

    form.addEventListener("change", function (event) {
      const control = event.target;
      if (!control.matches("[data-project-filter-technology]")) {
        return;
      }
      rememberTechnologyDropdown();
      submitFilterForm();
    });

    form.addEventListener("submit", function () {
      markUpdating();
      setPanelOpen(false);
      closeDropdowns();
    });

    if (searchForm) {
      searchForm.addEventListener("submit", function () {
        markUpdating();
        setPanelOpen(false);
        closeDropdowns();
      });
    }

    root.addEventListener("click", function (event) {
      const link = event.target.closest("a");
      if (link) {
        markUpdating();
      }
    });

    document.addEventListener("click", function (event) {
      if (!root.contains(event.target)) {
        closeDropdowns();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") {
        return;
      }
      const openToggle = root.querySelector(
        '[data-project-dropdown-toggle][aria-expanded="true"]',
      );
      if (!openToggle) {
        return;
      }
      const dropdown = openToggle.closest("[data-project-filter-dropdown]");
      setDropdownOpen(dropdown, false);
      openToggle.focus();
    });

    closeDropdowns();
    setPanelOpen(false);
    const rememberedDropdown = takeRememberedDropdown();
    if (rememberedDropdown) {
      restoreDropdown(rememberedDropdown);
    }
  }

  document.querySelectorAll("[data-project-filter-root]").forEach(setupProjectFilters);
  document.querySelectorAll("[data-project-category-nav]").forEach(setupCategoryScroller);
}());
