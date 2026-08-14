(function () {
    'use strict';

    function initializeGalleryControls() {
        const group = document.getElementById('gallery_items-group');
        if (!group) {
            return;
        }

        const tableBody = group.querySelector('tbody');
        const heading = group.querySelector('.inline-heading');
        if (!tableBody || !heading) {
            return;
        }

        const addAllButton = document.createElement('button');
        addAllButton.type = 'submit';
        addAllButton.name = '_gallery_add_all';
        addAllButton.value = '1';
        addAllButton.className = 'gallery-add-all';
        addAllButton.textContent = 'Add all';
        addAllButton.title = 'Add all ready images assigned to this project';
        heading.appendChild(addAllButton);

        function rows() {
            return Array.from(tableBody.querySelectorAll('tr.form-row:not(.empty-form)'))
                .filter((row) => !row.classList.contains('deleted'));
        }

        function syncPositions() {
            rows().forEach((row, index) => {
                const input = row.querySelector('.field-position input');
                if (input) {
                    input.value = index;
                }
            });
        }

        function updateButtons() {
            const currentRows = rows();
            currentRows.forEach((row, index) => {
                const controls = row.querySelector('.gallery-order-controls');
                if (!controls) {
                    return;
                }
                controls.querySelector('[data-gallery-move="up"]').disabled = index === 0;
                controls.querySelector('[data-gallery-move="down"]').disabled = index === currentRows.length - 1;
            });
        }

        function moveRow(row, direction) {
            const currentRows = rows();
            const index = currentRows.indexOf(row);
            const target = direction === 'up' ? currentRows[index - 1] : currentRows[index + 1];
            if (!target) {
                return;
            }
            if (direction === 'up') {
                tableBody.insertBefore(row, target);
            } else {
                tableBody.insertBefore(target, row);
            }
            syncPositions();
            updateButtons();
        }

        rows().forEach((row) => {
            const cell = row.querySelector('.field-position');
            const input = cell && cell.querySelector('input');
            if (!cell || !input || cell.querySelector('.gallery-order-controls')) {
                return;
            }

            input.type = 'hidden';
            const controls = document.createElement('span');
            controls.className = 'gallery-order-controls';
            controls.innerHTML = '<button type="button" data-gallery-move="up" aria-label="Move image up" title="Move image up">⌃</button>'
                + '<button type="button" data-gallery-move="down" aria-label="Move image down" title="Move image down">⌄</button>';
            controls.addEventListener('click', (event) => {
                const button = event.target.closest('button[data-gallery-move]');
                if (button) {
                    moveRow(row, button.dataset.galleryMove);
                }
            });
            cell.appendChild(controls);
        });

        syncPositions();
        updateButtons();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeGalleryControls);
    } else {
        initializeGalleryControls();
    }
}());
