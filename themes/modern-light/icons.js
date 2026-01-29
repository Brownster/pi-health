/**
 * Modern Light Theme Icons - Clean line icons, neutral colors, no fills
 */

const iconSVGs = {
    transfer: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><path d="M8 15V8m0 0L5 11m3-3l3 3m5-3v7m0 0l3-3m-3 3l-3-3" stroke="#3f3f46" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    search: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><circle cx="10.5" cy="10.5" r="3.5" stroke="#3f3f46" stroke-width="1.5"/><path d="M13 13l4 4" stroke="#3f3f46" stroke-width="1.5" stroke-linecap="round"/></svg>',

    tv: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><rect x="6" y="7" width="12" height="8" rx="1" stroke="#3f3f46" stroke-width="1.5" fill="none"/><path d="M10 17l-1 2m6-2l1 2" stroke="#3f3f46" stroke-width="1.5" stroke-linecap="round"/></svg>',

    film: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><rect x="6" y="7" width="12" height="10" rx="1" stroke="#3f3f46" stroke-width="1.5"/><line x1="6" y1="10" x2="18" y2="10" stroke="#3f3f46" stroke-width="1.5"/><line x1="6" y1="14" x2="18" y2="14" stroke="#3f3f46" stroke-width="1.5"/></svg>',

    download: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><path d="M12 7v8m0 0l-3-3m3 3l3-3m-6 5h6" stroke="#3f3f46" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    collection: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><rect x="7" y="7" width="10" height="4" rx="1" stroke="#3f3f46" stroke-width="1.5"/><rect x="7" y="13" width="10" height="4" rx="1" stroke="#3f3f46" stroke-width="1.5"/></svg>',

    play: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><path d="M10 8l6 4-6 4V8z" fill="none" stroke="#3f3f46" stroke-width="1.5" stroke-linejoin="round"/></svg>',

    'cloud-download': '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><path d="M8 13a3 3 0 013-3 3 3 0 016 0c1 0 2 1 2 2s-1 2-2 2H9c-1 0-2-1-2-2s1-2 2-2z" stroke="#3f3f46" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 13v4m0 0l-2-2m2 2l2-2" stroke="#3f3f46" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    music: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><path d="M9 16V8l6-2v10M9 16c0 1-1 2-2 2s-2-1-2-2 1-2 2-2 2 1 2 2zm6-2c0 1-1 2-2 2s-2-1-2-2 1-2 2-2 2 1 2 2z" stroke="#3f3f46" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    book: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><path d="M12 7v10M12 7c-1-1-2-1-3-1s-2 0-3 1v10c1-1 2-1 3-1s2 0 3 1M12 7c1-1 2-1 3-1s2 0 3 1v10c-1-1-2-1-3-1s-2 0-3 1" stroke="#3f3f46" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    default: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="3" width="18" height="18" rx="2" stroke="#d4d4d8" stroke-width="1.5" fill="none"/><rect x="7" y="7" width="10" height="4" rx="1" stroke="#3f3f46" stroke-width="1.5"/><circle cx="16" cy="13.5" r="0.5" fill="#3f3f46"/><circle cx="16" cy="16" r="0.5" fill="#3f3f46"/></svg>'
};

// Export for use
window.ThemeIcons = iconSVGs;
