/**
 * Мобильное меню — подключается сразу после разметки навбара на каждой странице.
 */
(function () {
    'use strict';

    function initMobileNav() {
        const navbar = document.getElementById('site-navbar');
        const toggle = document.getElementById('nav-toggle');
        const closeBtn = document.getElementById('nav-close');
        const overlay = document.getElementById('nav-overlay');
        const drawer = document.getElementById('nav-drawer');
        if (!navbar || !toggle || !overlay || !drawer) return;
        if (navbar.dataset.navBound === '1') return;
        navbar.dataset.navBound = '1';

        const openNav = () => {
            navbar.classList.add('nav-open');
            overlay.classList.add('visible');
            overlay.setAttribute('aria-hidden', 'false');
            toggle.setAttribute('aria-expanded', 'true');
            document.body.classList.add('nav-menu-open');
        };

        const closeNav = () => {
            navbar.classList.remove('nav-open');
            overlay.classList.remove('visible');
            overlay.setAttribute('aria-hidden', 'true');
            toggle.setAttribute('aria-expanded', 'false');
            document.body.classList.remove('nav-menu-open');
        };

        const onToggle = (e) => {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            if (navbar.classList.contains('nav-open')) {
                closeNav();
            } else {
                openNav();
            }
        };

        toggle.addEventListener('click', onToggle);

        if (closeBtn) {
            closeBtn.addEventListener('click', closeNav);
        }

        overlay.addEventListener('click', closeNav);

        drawer.querySelectorAll('.nav-menu a').forEach((link) => {
            link.addEventListener('click', closeNav);
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeNav();
        });

        window.addEventListener('resize', () => {
            if (window.innerWidth > 1024) closeNav();
        });
    }

    window.initMobileNav = initMobileNav;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initMobileNav);
    } else {
        initMobileNav();
    }
})();
