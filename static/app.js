/* ========================================
   彩票数据系统 - 全局JS v3.0
   ======================================== */
window.App = (function() {
    'use strict';

    // =====================================
    // 彩种配置
    // =====================================
    var LOTTERY_CONFIG = {
        '3d':  { name: '福彩3D',   color: '#e53935', icon: '🔴', digits: 3, type: 'digit' },
        'p3':  { name: '排列三',   color: '#f57c00', icon: '🟠', digits: 3, type: 'digit' },
        'p5':  { name: '排列五',   color: '#ffa000', icon: '🟡', digits: 5, type: 'digit' },
        'ssq': { name: '双色球',   color: '#1565c0', icon: '🔵', type: 'ssq' },
        'dlt': { name: '大乐透',   color: '#7b1fa2', icon: '🟣', type: 'dlt' },
        'qxc': { name: '七星彩',   color: '#00838f', icon: '䷀', digits: 7, type: 'digit' },
        '7lc': { name: '七乐彩',   color: '#c2185b', icon: '䷁', type: '7lc' },
        'kl8': { name: '快乐八',   color: '#2e7d32', icon: '🟢', type: 'kl8' }
    };

    // =====================================
    // Toast 通知系统
    // =====================================
    var toastContainer = null;

    function ensureToastContainer() {
        if (!toastContainer) {
            toastContainer = document.getElementById('toast-container');
            if (!toastContainer) {
                toastContainer = document.createElement('div');
                toastContainer.id = 'toast-container';
                toastContainer.className = 'toast-container';
                document.body.appendChild(toastContainer);
            }
        }
        return toastContainer;
    }

    function showToast(message, type) {
        type = type || 'info';
        var icons = { success: '✓', error: '✗', info: 'ℹ', warning: '⚠' };
        var container = ensureToastContainer();
        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.innerHTML = '<span class="toast-icon">' + (icons[type] || 'ℹ') + '</span>' +
            '<span class="toast-msg">' + message + '</span>' +
            '<button class="toast-close">&times;</button>';
        container.appendChild(toast);
        var closeBtn = toast.querySelector('.toast-close');
        closeBtn.addEventListener('click', function() { closeToast(toast); });
        setTimeout(function() { closeToast(toast); }, 3500);
    }

    function closeToast(toast) {
        if (toast.style.display === 'none') return;
        toast.style.animation = 'toastOut 0.3s ease-in forwards';
        setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
    }

    // =====================================
    // 工具函数
    // =====================================
    function formatDate(dateStr) {
        if (!dateStr) return '';
        return dateStr.replace(/-/g, '/');
    }

    function copyToClipboard(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function() {
                showToast('已复制到剪贴板', 'success');
            }).catch(function() { fallbackCopy(text); });
        } else {
            fallbackCopy(text);
        }
    }

    function fallbackCopy(text) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); showToast('已复制到剪贴板', 'success'); }
        catch (e) { showToast('复制失败', 'error'); }
        document.body.removeChild(ta);
    }

    function debounce(fn, delay) {
        var timer = null;
        return function() {
            var args = arguments;
            var ctx = this;
            clearTimeout(timer);
            timer = setTimeout(function() { fn.apply(ctx, args); }, delay);
        };
    }

    function getLotteryCode() {
        var body = document.body;
        return body.getAttribute('data-code') || '3d';
    }

    function getLotteryName(code) {
        var cfg = LOTTERY_CONFIG[code];
        return cfg ? cfg.name : code.toUpperCase();
    }

    function getLotteryColor(code) {
        var cfg = LOTTERY_CONFIG[code];
        return cfg ? cfg.color : '#4f6ef7';
    }

    // =====================================
    // 分页 URL 辅助
    // =====================================
    function pageUrl(page) {
        var path = window.location.pathname;
        var search = window.location.search;
        var params = new URLSearchParams(search);
        params.set('page', page);
        return path + '?' + params.toString();
    }

    // =====================================
    // 骨架屏
    // =====================================
    function showSkeleton(container, count) {
        if (!container) return;
        count = count || 5;
        var html = '';
        for (var i = 0; i < count; i++) {
            html += '<div style="display:flex;align-items:center;gap:8px;padding:10px 0;">' +
                '<div class="skeleton" style="width:80px;height:14px;"></div>' +
                '<div class="skeleton" style="width:60px;height:14px;"></div>' +
                '<div class="skeleton skeleton-ball" style="width:22px;height:22px;"></div>' +
                '<div class="skeleton skeleton-ball" style="width:22px;height:22px;"></div>' +
                '<div class="skeleton skeleton-ball" style="width:22px;height:22px;"></div>' +
                '</div>';
        }
        container.innerHTML = html;
    }

    // =====================================
    // 回到顶部
    // =====================================
    function initBackToTop() {
        var btn = document.getElementById('back-to-top');
        if (!btn) return;
        window.addEventListener('scroll', function() {
            if (window.scrollY > 300) {
                btn.classList.add('visible');
            } else {
                btn.classList.remove('visible');
            }
        });
        btn.addEventListener('click', function() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    // =====================================
    // 边栏控制
    // =====================================
    function initSidebar() {
        var collapseBtn = document.getElementById('sidebar-collapse');
        var hamburger = document.getElementById('hamburger');
        var overlay = document.getElementById('sidebar-overlay');
        var sidebar = document.querySelector('.sidebar');

        if (collapseBtn) {
            collapseBtn.addEventListener('click', function() {
                document.body.classList.toggle('sidebar-folded');
            });
        }

        if (hamburger && sidebar) {
            hamburger.addEventListener('click', function() {
                sidebar.classList.toggle('open');
                if (overlay) overlay.classList.toggle('show');
            });
        }

        if (overlay && sidebar) {
            overlay.addEventListener('click', function() {
                sidebar.classList.remove('open');
                overlay.classList.remove('show');
            });
        }
    }

    // =====================================
    // 双数字击复制
    // =====================================
    function initDoubleClickCopy() {
        document.addEventListener('dblclick', function(e) {
            var target = e.target;
            if (target.classList.contains('ball') || target.classList.contains('ball-sm') || target.classList.contains('num-cell')) {
                var text = target.textContent.trim();
                if (text) copyToClipboard(text);
            }
        });
    }

    // =====================================
    // 初始化
    // =====================================
    function init() {
        initBackToTop();
        initSidebar();
        initDoubleClickCopy();
    }

    // DOM 就绪后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // =====================================
    // 公开 API
    // =====================================
    return {
        toast: showToast,
        copy: copyToClipboard,
        formatDate: formatDate,
        debounce: debounce,
        getCode: getLotteryCode,
        getName: getLotteryName,
        getColor: getLotteryColor,
        pageUrl: pageUrl,
        showSkeleton: showSkeleton,
        config: LOTTERY_CONFIG
    };
})();