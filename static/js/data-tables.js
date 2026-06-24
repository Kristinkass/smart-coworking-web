/**
 * Подписи колонок для мобильных карточек таблиц (data-label из thead).
 */
(function (global) {
    'use strict';

    const TABLE_SELECTOR = [
        '.admin-table',
        '.reports-table',
        '.subscriptions-table',
        '.module-data-table',
        'table.notify-history-table',
        '.stats-table',
    ].join(', ');

    function labelFromTh(th) {
        return (th.textContent || '').replace(/\s+/g, ' ').trim();
    }

    function enhanceTable(table) {
        if (!table) return;

        const headerRows = table.querySelectorAll('thead tr');
        if (!headerRows.length) return;

        const lastHeader = headerRows[headerRows.length - 1];
        const headers = [...lastHeader.querySelectorAll('th')].map(labelFromTh);

        table.querySelectorAll('tbody tr').forEach((tr) => {
            const cells = tr.querySelectorAll(':scope > td');
            cells.forEach((td, i) => {
                if (td.colSpan > 1) return;
                if (headers[i]) {
                    td.dataset.label = headers[i];
                }
                const label = (td.dataset.label || '').toLowerCase();
                if (label.includes('действ') || td.querySelector('.action-buttons, .btn-action, .feedback-delete-btn')) {
                    td.classList.add('cw-td-actions');
                }
            });
        });

        table.classList.add('cw-data-table');
    }

    function enhanceAll(root) {
        const scope = root || document;
        if (root && root.tagName === 'TABLE') {
            enhanceTable(root);
            return;
        }
        scope.querySelectorAll(TABLE_SELECTOR).forEach(enhanceTable);
    }

    document.addEventListener('DOMContentLoaded', () => enhanceAll());

    global.enhanceDataTables = enhanceAll;
})(window);
