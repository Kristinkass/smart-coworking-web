/**
 * Themed toasts and confirm dialogs (olive coworking palette).
 */
(function (global) {
    'use strict';

    const ICONS = {
        success: 'fa-check-circle',
        error: 'fa-times-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle',
    };

    function ensureStyles() {
        if (document.getElementById('cw-notify-styles')) return;
        const style = document.createElement('style');
        style.id = 'cw-notify-styles';
        style.textContent = `
            #cw-toast-container {
                position: fixed;
                top: 80px;
                right: 20px;
                z-index: 10050;
                display: flex;
                flex-direction: column;
                gap: 10px;
                max-width: 380px;
                width: calc(100% - 40px);
                pointer-events: none;
            }
            .cw-toast {
                pointer-events: auto;
                display: flex;
                align-items: flex-start;
                gap: 12px;
                padding: 14px 16px;
                border-radius: 12px;
                background: #fdfdf9;
                border: 1px solid #dde3d4;
                border-left: 4px solid #8fa67a;
                box-shadow: 0 8px 24px rgba(47, 52, 40, 0.12);
                color: #2f3428;
                font-size: 14px;
                line-height: 1.45;
                animation: cwToastIn 0.28s ease-out;
            }
            .cw-toast.hiding { animation: cwToastOut 0.25s ease-in forwards; }
            .cw-toast i { margin-top: 2px; font-size: 18px; flex-shrink: 0; }
            .cw-toast-success { border-left-color: #4d8f5f; }
            .cw-toast-success i { color: #4d8f5f; }
            .cw-toast-error { border-left-color: #c75050; }
            .cw-toast-error i { color: #c75050; }
            .cw-toast-warning { border-left-color: #c9a84c; }
            .cw-toast-warning i { color: #c9a84c; }
            .cw-toast-info { border-left-color: #6b8f9e; }
            .cw-toast-info i { color: #6b8f9e; }
            .cw-toast-body { flex: 1; }
            .cw-toast-close {
                background: none;
                border: none;
                color: #5c6554;
                font-size: 20px;
                line-height: 1;
                cursor: pointer;
                padding: 0;
                opacity: 0.65;
            }
            .cw-toast-close:hover { opacity: 1; }
            @media (max-width: 768px) {
                #cw-toast-container {
                    top: 64px;
                    right: 8px;
                    gap: 5px;
                    max-width: 220px;
                    width: calc(100% - 16px);
                }
                .cw-toast {
                    gap: 6px;
                    padding: 7px 8px;
                    border-radius: 8px;
                    border-left-width: 3px;
                    font-size: 11px;
                    line-height: 1.35;
                    box-shadow: 0 4px 12px rgba(47, 52, 40, 0.12);
                }
                .cw-toast i {
                    font-size: 13px;
                }
                .cw-toast-close {
                    font-size: 14px;
                }
            }
            @keyframes cwToastIn {
                from { transform: translateX(110%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes cwToastOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(110%); opacity: 0; }
            }
            .cw-confirm-overlay {
                position: fixed;
                inset: 0;
                background: rgba(47, 52, 40, 0.45);
                z-index: 10060;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
                animation: cwFadeIn 0.2s ease-out;
            }
            .cw-confirm-box {
                background: #fdfdf9;
                border: 1px solid #dde3d4;
                border-radius: 16px;
                padding: 24px;
                max-width: 420px;
                width: 100%;
                box-shadow: 0 16px 40px rgba(47, 52, 40, 0.18);
            }
            .cw-confirm-box h4 {
                margin: 0 0 10px;
                font-size: 18px;
                color: #2f3428;
            }
            .cw-confirm-box p {
                margin: 0 0 20px;
                color: #5c6554;
                font-size: 15px;
                line-height: 1.5;
            }
            .cw-confirm-actions {
                display: flex;
                justify-content: flex-end;
                gap: 10px;
            }
            .cw-confirm-actions button {
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
            }
            .cw-btn-cancel {
                background: #eef1e8;
                color: #5c6554;
            }
            .cw-btn-cancel:hover { background: #e2e8d8; }
            .cw-btn-confirm {
                background: #8fa67a;
                color: #fff;
            }
            .cw-btn-confirm:hover { background: #6f855c; }
            .cw-btn-danger { background: #c75050; }
            .cw-btn-danger:hover { background: #a84040; }
            .cw-prompt-box .cw-prompt-input {
                width: 100%;
                box-sizing: border-box;
                margin: 0 0 16px;
                padding: 10px 12px;
                border: 1px solid #dde3d4;
                border-radius: 8px;
                font-size: 14px;
                font-family: inherit;
                color: #2f3428;
                resize: vertical;
            }
            .cw-prompt-box .cw-prompt-input:focus {
                outline: none;
                border-color: #8fa67a;
                box-shadow: 0 0 0 3px rgba(143, 166, 122, 0.2);
            }
            @keyframes cwFadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            @media (max-width: 768px) {
                #cw-toast-container { top: 60px; right: 10px; left: 10px; width: auto; max-width: none; }
            }
        `;
        document.head.appendChild(style);
    }

    function toastContainer() {
        let el = document.getElementById('cw-toast-container');
        if (!el) {
            el = document.createElement('div');
            el.id = 'cw-toast-container';
            document.body.appendChild(el);
        }
        return el;
    }

    function escapeHtml(text) {
        return String(text ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function showToast(message, type = 'info', duration = 4500) {
        ensureStyles();
        const kind = ['success', 'error', 'warning', 'info'].includes(type) ? type : 'info';
        const toast = document.createElement('div');
        toast.className = `cw-toast cw-toast-${kind}`;
        toast.innerHTML = `
            <i class="fas ${ICONS[kind]}"></i>
            <div class="cw-toast-body">${message}</div>
            <button type="button" class="cw-toast-close" aria-label="Закрыть">&times;</button>
        `;
        const close = () => {
            toast.classList.add('hiding');
            setTimeout(() => toast.remove(), 250);
        };
        toast.querySelector('.cw-toast-close').addEventListener('click', close);
        toastContainer().appendChild(toast);
        if (duration > 0) setTimeout(close, duration);
        return toast;
    }

    function showConfirm(message, options = {}) {
        ensureStyles();
        const {
            title = 'Подтверждение',
            confirmText = 'Да',
            cancelText = 'Отмена',
            danger = false,
        } = options;

        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'cw-confirm-overlay';
            overlay.innerHTML = `
                <div class="cw-confirm-box" role="dialog" aria-modal="true">
                    <h4>${escapeHtml(title)}</h4>
                    <p>${escapeHtml(message)}</p>
                    <div class="cw-confirm-actions">
                        <button type="button" class="cw-btn-cancel">${escapeHtml(cancelText)}</button>
                        <button type="button" class="cw-btn-confirm ${danger ? 'cw-btn-danger' : ''}">${escapeHtml(confirmText)}</button>
                    </div>
                </div>
            `;

            const finish = (value) => {
                overlay.remove();
                resolve(value);
            };

            overlay.querySelector('.cw-btn-cancel').addEventListener('click', () => finish(false));
            overlay.querySelector('.cw-btn-confirm').addEventListener('click', () => finish(true));
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) finish(false);
            });

            document.body.appendChild(overlay);
        });
    }

    function showPrompt(message, options = {}) {
        ensureStyles();
        const {
            title = 'Введите значение',
            confirmText = 'OK',
            cancelText = 'Отмена',
            placeholder = '',
            defaultValue = '',
            multiline = false,
        } = options;

        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'cw-confirm-overlay';
            const inputHtml = multiline
                ? `<textarea class="cw-prompt-input" rows="4" placeholder="${escapeHtml(placeholder)}">${escapeHtml(defaultValue)}</textarea>`
                : `<input type="text" class="cw-prompt-input" placeholder="${escapeHtml(placeholder)}" value="${escapeHtml(defaultValue)}">`;
            overlay.innerHTML = `
                <div class="cw-confirm-box cw-prompt-box" role="dialog" aria-modal="true">
                    <h4>${escapeHtml(title)}</h4>
                    <p>${escapeHtml(message)}</p>
                    ${inputHtml}
                    <div class="cw-confirm-actions">
                        <button type="button" class="cw-btn-cancel">${escapeHtml(cancelText)}</button>
                        <button type="button" class="cw-btn-confirm">${escapeHtml(confirmText)}</button>
                    </div>
                </div>
            `;

            const input = overlay.querySelector('.cw-prompt-input');
            const finish = (value) => {
                overlay.remove();
                resolve(value);
            };

            overlay.querySelector('.cw-btn-cancel').addEventListener('click', () => finish(null));
            overlay.querySelector('.cw-btn-confirm').addEventListener('click', () => {
                finish(input.value.trim() || null);
            });
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) finish(null);
            });
            input.addEventListener('keydown', (e) => {
                if (!multiline && e.key === 'Enter') {
                    e.preventDefault();
                    finish(input.value.trim() || null);
                }
            });

            document.body.appendChild(overlay);
            input.focus();
        });
    }

    global.showToast = showToast;
    global.showConfirm = showConfirm;
    global.showPrompt = showPrompt;
    global.showAlert = showToast;
    global.showBookingToast = showToast;
})(window);
