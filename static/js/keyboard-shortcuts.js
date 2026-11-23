/**
 * Keyboard Shortcuts System
 * اختصارات لوحة المفاتيح الاحترافية
 */

class KeyboardShortcuts {
    constructor() {
        this.shortcuts = new Map();
        this.isEnabled = true;
        this.init();
    }

    init() {
        document.addEventListener('keydown', this.handleKeyPress.bind(this));
        this.registerDefaultShortcuts();
        this.showHelpButton();
    }

    register(key, callback, description = '') {
        this.shortcuts.set(key.toLowerCase(), {
            callback,
            description
        });
    }

    handleKeyPress(e) {
        if (!this.isEnabled) return;
        
        // Don't trigger in input fields (unless Ctrl/Alt is pressed)
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) && 
            !e.ctrlKey && !e.altKey && !e.metaKey) {
            return;
        }

        const key = this.getKeyString(e);
        const shortcut = this.shortcuts.get(key);

        if (shortcut) {
            e.preventDefault();
            shortcut.callback(e);
        }
    }

    getKeyString(e) {
        const parts = [];
        if (e.ctrlKey || e.metaKey) parts.push('ctrl');
        if (e.altKey) parts.push('alt');
        if (e.shiftKey) parts.push('shift');
        parts.push(e.key.toLowerCase());
        return parts.join('+');
    }

    registerDefaultShortcuts() {
        // Navigation
        this.register('alt+h', () => {
            window.location.href = '/';
        }, t('Go to Home'));

        this.register('alt+s', () => {
            const salesBtn = document.querySelector('a[href*="sales"]');
            if (salesBtn) salesBtn.click();
        }, t('Open Sales'));

        this.register('alt+c', () => {
            const customersBtn = document.querySelector('a[href*="customers"]');
            if (customersBtn) customersBtn.click();
        }, t('Open Customers'));

        this.register('alt+p', () => {
            const productsBtn = document.querySelector('a[href*="products"]');
            if (productsBtn) productsBtn.click();
        }, t('Open Products'));

        // Actions
        this.register('ctrl+n', () => {
            const createBtn = document.querySelector('.btn-primary[href*="create"]');
            if (createBtn) {
                createBtn.click();
            } else {
                notify.info(t('No create button on this page'));
            }
        }, t('Create New'));

        this.register('ctrl+s', (e) => {
            const form = document.querySelector('form');
            if (form) {
                form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            }
        }, t('Save Form'));

        this.register('escape', () => {
            // Close modals
            const modal = document.querySelector('.modal.show');
            if (modal) {
                $(modal).modal('hide');
                return;
            }

            // Close notifications
            const toasts = document.querySelectorAll('.toast');
            toasts.forEach(toast => toast.remove());
        }, t('Close/Cancel'));

        // Search
        this.register('ctrl+k', () => {
            const searchInput = document.querySelector('input[type="search"], input[placeholder*="بحث"]');
            if (searchInput) {
                searchInput.focus();
                searchInput.select();
            }
        }, t('Quick Search'));

        // DataTable shortcuts
        this.register('ctrl+e', () => {
            const exportBtn = document.querySelector('.buttons-excel, .buttons-csv');
            if (exportBtn) {
                exportBtn.click();
                notify.success(t('Exporting data...'));
            }
        }, t('Export Data'));

        this.register('ctrl+p', () => {
            window.print();
        }, t('Print'));

        // Help
        this.register('?', () => {
            this.showHelp();
        }, t('Show Help'));

        this.register('ctrl+/', () => {
            this.showHelp();
        }, t('Show Shortcuts'));

        // Sidebar toggle
        this.register('ctrl+b', () => {
            $('[data-widget="pushmenu"]').trigger('click');
        }, t('Hide/Show Menu'));
    }

    showHelpButton() {
        // No floating button: the help is reachable from the navbar
        // (#shortcuts-nav-btn) next to the theme toggle. Keep a no-op here
        // so older callers don't break.
    }

    showHelp() {
        const shortcuts = Array.from(this.shortcuts.entries())
            .filter(([_, v]) => v.description)
            .map(([key, value]) => `
                <tr>
                    <td><kbd class="shortcut-key">${key}</kbd></td>
                    <td>${value.description}</td>
                </tr>
            `).join('');

        const modal = `
            <div class="modal fade" id="shortcuts-modal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header bg-info text-white">
                            <h5 class="modal-title">
                                <i class="fas fa-keyboard mr-2"></i>
                                ${t('Keyboard Shortcuts')}
                            </h5>
                            <button type="button" class="close text-white" data-dismiss="modal">
                                <span>×</span>
                            </button>
                        </div>
                        <div class="modal-body">
                            <table class="table table-hover">
                                <thead>
                                    <tr>
                                        <th style="width: 200px">${t('Shortcut')}</th>
                                        <th>${t('Description')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${shortcuts}
                                </tbody>
                            </table>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">${t('Close')}</button>
                        </div>
                    </div>
                </div>
            </div>
            <style>
                .shortcut-key {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 4px 8px;
                    border-radius: 5px;
                    font-size: 12px;
                    font-weight: 600;
                    margin: 0 2px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                    white-space: nowrap;
                }
            </style>
        `;

        // Guard: Bootstrap modal may be unavailable on some pages/loads.
        if (typeof $ === 'undefined' || !$.fn || !$.fn.modal) return;
        // Remove old modal
        $('#shortcuts-modal').remove();

        // Add and show new modal
        $(modal).appendTo('body').modal('show');
    }

    disable() {
        this.isEnabled = false;
    }

    enable() {
        this.isEnabled = true;
    }
}

// Initialize
window.shortcuts = new KeyboardShortcuts();

// Navbar entry point for the shortcuts help (replaces the old floating button)
document.addEventListener('DOMContentLoaded', function() {
    const host = document.querySelector('.navbar-widgets') ||
                 document.querySelector('.main-header .navbar-nav.ml-auto') ||
                 document.querySelector('.main-header .navbar-nav');
    if (!host || document.getElementById('shortcuts-nav-btn')) return;
    const li = document.createElement('li');
    li.className = 'nav-item d-flex align-items-center px-2';
    const btn = document.createElement('button');
    btn.id = 'shortcuts-nav-btn';
    btn.className = 'btn btn-sm btn-link text-white';
    btn.innerHTML = '<i class="fas fa-keyboard"></i>';
    btn.title = t('Keyboard Shortcuts (?)');
    btn.onclick = function() { window.shortcuts && window.shortcuts.showHelp(); };
    li.appendChild(btn);
    host.insertBefore(li, host.firstChild);
});

// First-load tip is optional; never let a missing notifier break the page.
document.addEventListener('DOMContentLoaded', function() {
    try {
        if (typeof notify !== 'undefined' && notify && notify.info &&
            !localStorage.getItem('shortcuts-shown')) {
            setTimeout(function() {
                notify.info(t('Press ? to show keyboard shortcuts'), t('Quick Tip'));
                localStorage.setItem('shortcuts-shown', 'true');
            }, 2000);
        }
    } catch (e) { /* non-critical */ }
});

