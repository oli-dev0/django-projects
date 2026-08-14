(function () {
    'use strict';

    function initializeProjectReorder() {
        const form = document.querySelector('[data-project-reorder-form]');
        const list = form && form.querySelector('[data-project-reorder-list]');
        const saveButton = form && form.querySelector('[data-project-reorder-save]');
        const announcement = form && form.querySelector('[data-project-reorder-announcement]');
        if (!form || !list || !saveButton) {
            return;
        }

        const initialOrder = itemIds();
        let draggedItem = null;

        function items() {
            return Array.from(list.querySelectorAll('[data-project-reorder-item]'));
        }

        function itemIds() {
            return items().map((item) => item.querySelector('input[name="project_id"]').value);
        }

        function announce(item, position) {
            if (!announcement) {
                return;
            }
            const title = item.querySelector('.project-reorder-admin__details strong').textContent.trim();
            announcement.textContent = form.dataset.movedAnnouncement
                .replace('{title}', title)
                .replace('{position}', position);
        }

        function synchronize({ movedItem = null } = {}) {
            const currentItems = items();
            currentItems.forEach((item, index) => {
                item.querySelector('[data-project-position]').textContent = index + 1;
                item.querySelector('[data-project-move="up"]').disabled = index === 0;
                item.querySelector('[data-project-move="down"]').disabled = index === currentItems.length - 1;
            });
            saveButton.disabled = itemIds().every((id, index) => id === initialOrder[index]);
            if (movedItem) {
                announce(movedItem, currentItems.indexOf(movedItem) + 1);
            }
        }

        function move(item, direction) {
            const currentItems = items();
            const index = currentItems.indexOf(item);
            const target = direction === 'up' ? currentItems[index - 1] : currentItems[index + 1];
            if (!target) {
                return;
            }
            if (direction === 'up') {
                list.insertBefore(item, target);
            } else {
                list.insertBefore(target, item);
            }
            synchronize({ movedItem: item });
        }

        list.addEventListener('click', (event) => {
            const button = event.target.closest('[data-project-move]');
            if (button) {
                move(button.closest('[data-project-reorder-item]'), button.dataset.projectMove);
            }
        });

        list.addEventListener('dragstart', (event) => {
            const item = event.target.closest('[data-project-reorder-item]');
            if (!item || !event.target.closest('[data-project-drag-handle]')) {
                event.preventDefault();
                return;
            }
            draggedItem = item;
            item.classList.add('project-reorder-admin__item--dragging');
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', item.querySelector('input[name="project_id"]').value);
            event.dataTransfer.setDragImage(item, 12, 12);
        });

        list.addEventListener('dragover', (event) => {
            if (!draggedItem) {
                return;
            }
            event.preventDefault();
            const target = event.target.closest('[data-project-reorder-item]');
            if (!target || target === draggedItem) {
                return;
            }
            const bounds = target.getBoundingClientRect();
            const insertAfter = event.clientY > bounds.top + bounds.height / 2;
            list.insertBefore(draggedItem, insertAfter ? target.nextSibling : target);
        });

        list.addEventListener('drop', (event) => {
            if (draggedItem) {
                event.preventDefault();
            }
        });

        list.addEventListener('dragend', () => {
            if (!draggedItem) {
                return;
            }
            draggedItem.classList.remove('project-reorder-admin__item--dragging');
            const movedItem = draggedItem;
            draggedItem = null;
            synchronize({ movedItem });
        });

        synchronize();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeProjectReorder);
    } else {
        initializeProjectReorder();
    }
}());
