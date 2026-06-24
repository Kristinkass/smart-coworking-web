/**
 * Счётчик новых обращений клиентов для менеджера и администратора.
 */
(function () {
    function applyBadge(el, count) {
        if (!el) return;
        if (count > 0) {
            el.hidden = false;
            el.textContent = count > 9 ? '9+' : String(count);
        } else {
            el.hidden = true;
        }
    }

    window.refreshStaffFeedbackIndicators = async function () {
        try {
            const response = await fetch('/api/notifications');
            const data = await response.json();
            if (!response.ok || data.error) return null;
            const count = typeof data.feedback_unread_count === 'number'
                ? data.feedback_unread_count
                : 0;
            document.querySelectorAll('[data-staff-feedback-badge]').forEach(el => {
                applyBadge(el, count);
            });
            return count;
        } catch (e) {
            console.error(e);
            return null;
        }
    };

    document.addEventListener('DOMContentLoaded', () => {
        if (document.querySelector('[data-staff-feedback-badge]')) {
            refreshStaffFeedbackIndicators();
            setInterval(() => {
                if (!document.hidden) refreshStaffFeedbackIndicators();
            }, 45000);
        }
    });
})();
