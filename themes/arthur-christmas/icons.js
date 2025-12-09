/**
 * Arthur Christmas Theme Icons - Festive holiday style
 */

const iconSVGs = {
    transfer: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" fill="#dc2626" stroke="#16a34a" stroke-width="2"/><circle cx="12" cy="12" r="4" fill="#fbbf24" stroke="#f59e0b" stroke-width="1.5"/><path d="M8 15V9m0 0L5 12m3-3l3 3m5-3v6m0 0l3-3m-3 3l-3-3" stroke="#fef3c7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    search: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" fill="#dc2626" stroke="#16a34a" stroke-width="2"/><path d="M12 5l1 2h2l-1.5 1.5L14 10l-2-1-2 1 .5-1.5L9 7h2l1-2z" fill="#fbbf24" stroke="#f59e0b" stroke-width="0.5"/><circle cx="10.5" cy="13.5" r="2.5" stroke="#fef3c7" stroke-width="1.5"/><path d="M12.5 15.5l3 3" stroke="#fef3c7" stroke-width="1.5" stroke-linecap="round"/></svg>',

    tv: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="4" y="4" width="16" height="16" rx="2" stroke="#16a34a" stroke-width="2" fill="#dc2626" fill-opacity="0.3"/><rect x="7" y="8" width="10" height="6" rx="1" stroke="#fef3c7" stroke-width="1.5"/><circle cx="9" cy="17" r="1" fill="#fbbf24"/><circle cx="15" cy="17" r="1" fill="#fbbf24"/><path d="M12 5l.5 1h1l-.8.6.3 1-.8-.6-.8.6.3-1-.8-.6h1l.5-1z" fill="#fbbf24" stroke="none"/></svg>',

    film: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="4" y="4" width="16" height="16" rx="2" stroke="#16a34a" stroke-width="2" fill="#dc2626" fill-opacity="0.3"/><rect x="7" y="7" width="10" height="10" rx="1" stroke="#fef3c7" stroke-width="1.5"/><line x1="7" y1="10" x2="17" y2="10" stroke="#fef3c7" stroke-width="1"/><line x1="7" y1="14" x2="17" y2="14" stroke="#fef3c7" stroke-width="1"/><circle cx="8.5" cy="8.5" r="0.5" fill="#fbbf24"/><circle cx="15.5" cy="15.5" r="0.5" fill="#fbbf24"/></svg>',

    download: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="5" y="8" width="14" height="11" rx="1" stroke="#16a34a" stroke-width="2" fill="#dc2626" fill-opacity="0.3"/><path d="M12 5v7m0 0l-3-3m3 3l3-3" stroke="#fef3c7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><rect x="8" y="16" width="8" height="1" fill="#fbbf24"/><path d="M12 5l.3.6.7.1-.5.5.1.7-.6-.3-.6.3.1-.7-.5-.5.7-.1.3-.6z" fill="#fbbf24"/></svg>',

    collection: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="4" y="4" width="16" height="16" rx="2" stroke="#16a34a" stroke-width="2" fill="#dc2626" fill-opacity="0.3"/><rect x="7" y="8" width="10" height="3" rx="0.5" stroke="#fef3c7" stroke-width="1.5"/><rect x="7" y="13" width="10" height="3" rx="0.5" stroke="#fef3c7" stroke-width="1.5"/><circle cx="9" cy="9.5" r="0.5" fill="#fbbf24"/><circle cx="9" cy="14.5" r="0.5" fill="#fbbf24"/></svg>',

    play: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" fill="#dc2626" stroke="#16a34a" stroke-width="2"/><circle cx="12" cy="12" r="5.5" stroke="#fbbf24" stroke-width="1" fill="none"/><path d="M10.5 9l4.5 3-4.5 3V9z" fill="#fef3c7" stroke="#fef3c7" stroke-width="1" stroke-linejoin="round"/></svg>',

    'cloud-download': '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><ellipse cx="12" cy="10" rx="8" ry="6" fill="#ffffff" fill-opacity="0.9" stroke="#16a34a" stroke-width="1.5"/><ellipse cx="9" cy="9" rx="3" ry="2" fill="#ffffff" stroke="#16a34a" stroke-width="1"/><ellipse cx="15" cy="9" rx="3" ry="2" fill="#ffffff" stroke="#16a34a" stroke-width="1"/><path d="M12 11v6m0 0l-2-2m2 2l2-2" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 5l.3.6.6.1-.4.4.1.6-.6-.3-.6.3.1-.6-.4-.4.6-.1.3-.6z" fill="#fbbf24"/></svg>',

    music: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" fill="#dc2626" stroke="#16a34a" stroke-width="2"/><path d="M9 15V9l6-2v8M9 15c0 1-1 1.5-2 1.5s-2-.5-2-1.5 1-1.5 2-1.5 2 .5 2 1.5zm6-2c0 1-1 1.5-2 1.5s-2-.5-2-1.5 1-1.5 2-1.5 2 .5 2 1.5z" stroke="#fef3c7" stroke-width="1.5" fill="none"/><circle cx="12" cy="6" r="1.5" fill="#fbbf24" stroke="#f59e0b" stroke-width="0.5"/></svg>',

    book: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="4" y="4" width="16" height="16" rx="1" stroke="#16a34a" stroke-width="2" fill="#dc2626" fill-opacity="0.3"/><path d="M12 7v10M12 7c-1-.7-2-1-3-1s-2 .3-3 1v10c1-.7 2-1 3-1s2 .3 3 1M12 7c1-.7 2-1 3-1s2 .3 3 1v10c-1-.7-2-1-3-1s-2 .3-3 1" stroke="#fef3c7" stroke-width="1.5"/><rect x="11.5" y="5" width="1" height="1.5" fill="#fbbf24"/><path d="M12 5l.3.6.6.1-.4.4.1.6-.6-.3-.6.3.1-.6-.4-.4.6-.1.3-.6z" fill="#fbbf24" transform="translate(0, -1)"/></svg>',

    default: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" fill="#dc2626" stroke="#16a34a" stroke-width="2"/><rect x="8" y="10" width="8" height="4" rx="0.5" stroke="#fef3c7" stroke-width="1.5"/><circle cx="10" cy="14" r="0.5" fill="#fbbf24"/><circle cx="14" cy="14" r="0.5" fill="#fbbf24"/><path d="M12 6l.5 1h1l-.8.6.3 1-.8-.6-.8.6.3-1-.8-.6h1l.5-1z" fill="#fbbf24" stroke="none"/></svg>'
};

// Export for use
window.ThemeIcons = iconSVGs;
