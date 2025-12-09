/**
 * Coraline Theme Icons - Button-eyed style
 */

const iconSVGs = {
    transfer: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    search: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    tv: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    film: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    download: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    collection: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    play: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    'cloud-download': '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    music: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    book: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',

    default: '<svg class="w-10 h-10" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" fill="#5f4b8b" stroke="#8a6cbd" stroke-width="1.5"/><path d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" stroke="#c9b6e6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
};

// Export for use
window.ThemeIcons = iconSVGs;
