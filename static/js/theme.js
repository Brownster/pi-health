/**
 * Theme Loader - Fetches and applies theme configuration dynamically
 */

let currentTheme = null;

async function loadTheme() {
    try {
        const response = await fetch('/api/theme');
        currentTheme = await response.json();
        applyTheme(currentTheme);
        await loadThemeIcons(currentTheme);
        return currentTheme;
    } catch (error) {
        console.error('Error loading theme:', error);
        // Fallback to default theme
        currentTheme = getDefaultTheme();
        applyTheme(currentTheme);
        await loadThemeIcons(currentTheme);
        return currentTheme;
    }
}

async function loadThemeIcons(theme) {
    // Load theme-specific icons if available
    if (theme.icons && theme.icons.file) {
        const themeName = theme.name;
        const iconsPath = `/themes/${themeName}/${theme.icons.file}`;

        try {
            // Dynamically load the icons script
            const script = document.createElement('script');
            script.src = iconsPath;
            script.async = false;

            return new Promise((resolve, reject) => {
                script.onload = () => {
                    console.log(`Loaded ${theme.icons.style} icons for ${theme.display_name} theme`);
                    resolve();
                };
                script.onerror = () => {
                    console.warn(`Failed to load icons from ${iconsPath}, using defaults`);
                    resolve(); // Don't reject, just continue with defaults
                };
                document.head.appendChild(script);
            });
        } catch (error) {
            console.warn('Error loading theme icons:', error);
        }
    }
}

function getDefaultTheme() {
    return {
        name: "default",
        display_name: "Default",
        title: "Pi-Health Dashboard",
        banner: { filename: "banner.jpg", alt_text: "Dashboard" },
        colors: {
            primary: "#5f4b8b",
            primary_light: "#6f58a3",
            primary_dark: "#372b53",
            accent: "#8a6cbd",
            accent_light: "#c9b6e6",
            background: "#111827",
            background_secondary: "#1f2937",
            background_tertiary: "#374151",
            text_primary: "#dbeafe",
            text_secondary: "#93c5fd",
            text_muted: "#6b7280",
            success: "#10b981",
            warning: "#f59e0b",
            error: "#ef4444",
            info: "#3b82f6",
            border: "#374151",
            border_light: "#4b5563",
            input_background: "#1f2937",
            ring: "#5f4b8b"
        },
        gradients: {
            header: "from-purple-900 to-blue-900",
            button: "from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700",
            card_options: [
                "from-purple-800 to-indigo-900",
                "from-indigo-800 to-purple-900",
                "from-blue-800 to-purple-900",
                "from-purple-900 to-blue-800",
                "from-indigo-900 to-blue-900",
                "from-blue-900 to-indigo-900"
            ]
        },
        effects: {
            card_glow: "0 0 20px rgba(139, 92, 246, 0.3)",
            card_hover_glow: "0 0 30px rgba(139, 92, 246, 0.5)",
            text_shadow: "2px 2px 4px rgba(0, 0, 0, 0.5)",
            card_border_radius: "0.5rem",
            button_border_radius: "0.375rem",
            transition_speed: "200ms"
        },
        typography: {},
        components: {},
        status_colors: {}
    };
}

function applyTheme(theme) {
    // Update page title — only replace the base dashboard name, preserve page-specific prefixes
    const titleElement = document.querySelector('title');
    if (titleElement && theme.title) {
        const currentTitle = titleElement.textContent;
        const dashIndex = currentTitle.indexOf(' - ');
        if (dashIndex > -1) {
            // Keep the page prefix (e.g. "Disks - ") and replace the base title
            titleElement.textContent = currentTitle.substring(0, dashIndex + 3) + theme.title;
        } else {
            titleElement.textContent = theme.title;
        }
    }

    // Update header title
    const headerTitle = document.querySelector('header h1');
    if (headerTitle && theme.title) {
        headerTitle.textContent = theme.title;
    }

    // Update banner image
    const bannerImage = document.querySelector('header img[alt]');
    if (bannerImage) {
        bannerImage.src = '/theme-banner';
        if (theme.banner && theme.banner.alt_text) {
            bannerImage.alt = theme.banner.alt_text;
        }
    }

    // Inject dynamic CSS
    injectThemeCSS(theme);
}

function injectThemeCSS(theme) {
    const colors = theme.colors || {};
    const effects = theme.effects || {};
    const typography = theme.typography || {};
    const components = theme.components || {};
    const gradients = theme.gradients || {};
    const statusColors = theme.status_colors || {};

    // Resolve with defaults
    const bg = colors.background || '#111827';
    const bgSecondary = colors.background_secondary || '#1f2937';
    const bgTertiary = colors.background_tertiary || '#374151';
    const textPrimary = colors.text_primary || '#dbeafe';
    const textSecondary = colors.text_secondary || '#93c5fd';
    const textMuted = colors.text_muted || '#6b7280';
    const primary = colors.primary || '#5f4b8b';
    const primaryLight = colors.primary_light || '#6f58a3';
    const primaryDark = colors.primary_dark || '#372b53';
    const accent = colors.accent || '#8a6cbd';
    const accentLight = colors.accent_light || '#c9b6e6';
    const border = colors.border || '#374151';
    const borderLight = colors.border_light || '#4b5563';
    const inputBg = colors.input_background || bgSecondary;
    const ring = colors.ring || primary;
    const success = colors.success || '#10b981';
    const warning = colors.warning || '#f59e0b';
    const error = colors.error || '#ef4444';
    const info = colors.info || '#3b82f6';

    const cardGlow = effects.card_glow || '0 0 20px rgba(139, 92, 246, 0.3)';
    const cardHoverGlow = effects.card_hover_glow || '0 0 30px rgba(139, 92, 246, 0.5)';
    const textShadow = effects.text_shadow || '2px 2px 4px rgba(0, 0, 0, 0.5)';
    const cardBorderRadius = effects.card_border_radius || '0.5rem';
    const buttonBorderRadius = effects.button_border_radius || '0.375rem';
    const transitionSpeed = effects.transition_speed || '200ms';

    // Component overrides
    const navBg = components.nav_background || bg;
    const navBorder = components.nav_border || border;
    const navLinkColor = components.nav_link_color || textSecondary;
    const navLinkHover = components.nav_link_hover || textPrimary;
    const navActiveBg = components.nav_active_bg || primaryDark;
    const navActiveColor = components.nav_active_color || '#ffffff';
    const navActiveBorder = components.nav_active_border || primaryLight;
    const navDropdownBg = components.nav_dropdown_bg || bgSecondary;
    const navDropdownBorder = components.nav_dropdown_border || border;

    const cardBg = components.card_background || bgSecondary;
    const cardBorder = components.card_border || border;
    const cardHoverBorder = components.card_hover_border || borderLight;
    const cardHeaderBg = components.card_header_bg || bgSecondary;

    const btnPrimaryBg = components.button_primary_bg || primary;
    const btnPrimaryHover = components.button_primary_hover || primaryDark;
    const btnPrimaryText = components.button_primary_text || '#ffffff';
    const btnSecondaryBg = components.button_secondary_bg || bgTertiary;
    const btnSecondaryHover = components.button_secondary_hover || borderLight;
    const btnSecondaryText = components.button_secondary_text || textPrimary;
    const btnDangerBg = components.button_danger_bg || '#dc2626';
    const btnDangerHover = components.button_danger_hover || '#b91c1c';

    const toggleOff = components.toggle_off || borderLight;
    const toggleOn = components.toggle_on || primary;

    const progressBg = components.progress_bar_bg || bgTertiary;
    const progressFill = components.progress_bar_fill || primary;

    const modalBackdrop = components.modal_backdrop || 'rgba(0, 0, 0, 0.5)';
    const modalBg = components.modal_bg || bgSecondary;
    const modalBorder = components.modal_border || border;

    const inputBorder = components.input_border || border;
    const inputFocusBorder = components.input_focus_border || primary;
    const inputBackground = components.input_bg || inputBg;

    const toastSuccessBg = components.toast_success_bg || '#065f46';
    const toastSuccessBorder = components.toast_success_border || success;
    const toastErrorBg = components.toast_error_bg || '#7f1d1d';
    const toastErrorBorder = components.toast_error_border || error;
    const toastWarningBg = components.toast_warning_bg || '#78350f';
    const toastWarningBorder = components.toast_warning_border || warning;
    const toastInfoBg = components.toast_info_bg || '#1e3a5f';
    const toastInfoBorder = components.toast_info_border || info;
    const toastText = components.toast_text || '#ffffff';

    const codeBg = components.code_bg || bg;
    const codeBorder = components.code_border || border;

    const spinnerColor = components.loading_spinner_color || primary;

    // Status colors
    const statusRunning = statusColors.running || success;
    const statusExited = statusColors.exited || error;
    const statusPaused = statusColors.paused || warning;
    const statusRestarting = statusColors.restarting || info;
    const statusCreated = statusColors.created || accent;
    const statusRemoving = statusColors.removing || '#f97316';
    const statusDead = statusColors.dead || '#991b1b';

    // Determine if gradients are "none" (flat mode)
    const isFlat = gradients.header === 'none';
    const isButtonFlat = gradients.button === 'none';

    // Create or update dynamic style element
    let styleElement = document.getElementById('dynamic-theme-styles');
    if (!styleElement) {
        styleElement = document.createElement('style');
        styleElement.id = 'dynamic-theme-styles';
        document.head.appendChild(styleElement);
    }

    // Font import (only if typography specifies a web font)
    let fontImport = '';
    if (typography.font_family && typography.font_family.includes('Inter')) {
        fontImport = `@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');`;
    }

    const css = `
        ${fontImport}

        /* ===== ROOT VARIABLES ===== */
        :root {
            --theme-primary: ${primary};
            --theme-primary-light: ${primaryLight};
            --theme-primary-dark: ${primaryDark};
            --theme-accent: ${accent};
            --theme-accent-light: ${accentLight};
            --theme-background: ${bg};
            --theme-background-secondary: ${bgSecondary};
            --theme-background-tertiary: ${bgTertiary};
            --theme-text-primary: ${textPrimary};
            --theme-text-secondary: ${textSecondary};
            --theme-text-muted: ${textMuted};
            --theme-border: ${border};
            --theme-border-light: ${borderLight};
            --theme-ring: ${ring};
            --theme-success: ${success};
            --theme-warning: ${warning};
            --theme-error: ${error};
            --theme-info: ${info};
            --theme-card-bg: ${cardBg};
            --theme-card-border: ${cardBorder};
            --theme-input-bg: ${inputBackground};
            --theme-input-border: ${inputBorder};
            --theme-nav-bg: ${navBg};
            --theme-nav-border: ${navBorder};
            --theme-nav-link-color: ${navLinkColor};
            --theme-nav-link-hover: ${navLinkHover};
            --theme-nav-active-bg: ${navActiveBg};
            --theme-nav-active-color: ${navActiveColor};
            --theme-nav-active-border: ${navActiveBorder};
            --theme-nav-dropdown-bg: ${navDropdownBg};
            --theme-nav-dropdown-border: ${navDropdownBorder};
            --theme-card-border-radius: ${cardBorderRadius};
            --theme-button-border-radius: ${buttonBorderRadius};
            --theme-transition-speed: ${transitionSpeed};
            --theme-spinner-color: ${spinnerColor};
        }

        /* ===== BODY & PAGE ===== */
        body {
            background-color: ${bg} !important;
            color: ${textPrimary} !important;
            ${typography.font_family ? `font-family: ${typography.font_family} !important;` : ''}
            ${typography.body_weight ? `font-weight: ${typography.body_weight};` : ''}
        }

        /* Override Tailwind bg-gray-900/bg-gray-950 on body and main containers */
        [class*="bg-gray-900"], [class*="bg-gray-950"] {
            background-color: ${bg} !important;
        }

        /* Override secondary backgrounds */
        [class*="bg-gray-800"] {
            background-color: ${bgSecondary} !important;
        }

        [class*="bg-gray-700"] {
            background-color: ${bgTertiary} !important;
        }

        /* ===== HEADER ===== */
        header, [class*="bg-gradient-to-r"][class*="from-purple"],
        [class*="bg-gradient-to-r"][class*="from-slate"],
        [class*="bg-gradient-to-r"][class*="from-blue"] {
            ${isFlat ? `background: ${bg} !important;` : ''}
            ${isFlat ? 'background-image: none !important;' : ''}
        }

        ${isFlat ? `
        header {
            border-bottom: 1px solid ${border} !important;
        }
        ` : ''}

        /* Header text */
        header h1 {
            ${textShadow === 'none' ? 'text-shadow: none !important;' : `text-shadow: ${textShadow} !important;`}
            ${typography.heading_weight ? `font-weight: ${typography.heading_weight} !important;` : ''}
            color: ${textPrimary} !important;
        }

        /* ===== NAVIGATION ===== */
        nav, #main-nav {
            background-color: ${navBg} !important;
            border-bottom: 1px solid ${navBorder} !important;
        }

        [class*="bg-purple-900"] {
            background-color: ${navBg} !important;
        }

        /* ===== CARDS ===== */
        .service-card {
            background-color: ${cardBg} !important;
            border-color: ${cardBorder} !important;
            border-radius: ${cardBorderRadius} !important;
            ${cardGlow === 'none' ? 'box-shadow: none !important;' : `box-shadow: ${cardGlow} !important;`}
            transition: all ${transitionSpeed} ease !important;
        }

        .service-card:hover {
            ${cardHoverGlow === 'none' ? 'box-shadow: none !important;' : `box-shadow: ${cardHoverGlow} !important;`}
            border-color: ${cardHoverBorder} !important;
        }

        /* Card gradient overrides - make them solid if flat */
        ${isFlat ? `
        [class*="from-purple-800"], [class*="from-indigo-800"],
        [class*="from-blue-800"], [class*="from-purple-900"],
        [class*="from-indigo-900"], [class*="from-blue-900"],
        [class*="from-slate-800"], [class*="from-cyan-800"],
        [class*="from-slate-900"], [class*="from-cyan-900"] {
            background: ${cardBg} !important;
            background-image: none !important;
        }
        ` : ''}

        /* ===== BUTTONS ===== */
        .coraline-button, .theme-button {
            ${isButtonFlat
                ? `background: ${btnPrimaryBg} !important; background-image: none !important;`
                : `background: linear-gradient(to bottom, ${primary}, ${primaryDark}) !important;`}
            border-color: ${isButtonFlat ? btnPrimaryBg : accent} !important;
            color: ${btnPrimaryText} !important;
            border-radius: ${buttonBorderRadius} !important;
            transition: all ${transitionSpeed} ease !important;
        }

        .coraline-button:hover, .theme-button:hover {
            ${isButtonFlat
                ? `background: ${btnPrimaryHover} !important;`
                : `background: linear-gradient(to bottom, ${primaryLight}, ${primary}) !important;`}
        }

        /* Secondary/outline buttons */
        [class*="bg-gray-600"], [class*="bg-gray-700"]:is(button, [role="button"], a[class*="btn"]) {
            background-color: ${btnSecondaryBg} !important;
            color: ${btnSecondaryText} !important;
        }

        /* Danger buttons */
        [class*="bg-red-600"]:is(button, [role="button"]) {
            background-color: ${btnDangerBg} !important;
        }
        [class*="bg-red-600"]:is(button, [role="button"]):hover {
            background-color: ${btnDangerHover} !important;
        }

        /* ===== TEXT COLORS ===== */
        [class*="text-blue-100"], [class*="text-blue-200"] {
            color: ${textSecondary} !important;
        }

        [class*="text-gray-400"], [class*="text-gray-500"] {
            color: ${textMuted} !important;
        }

        [class*="text-gray-300"], [class*="text-gray-200"] {
            color: ${textSecondary} !important;
        }

        [class*="text-blue-300"], [class*="text-blue-400"] {
            color: ${textSecondary} !important;
        }

        /* ===== BORDERS ===== */
        [class*="border-purple"], [class*="border-indigo"] {
            border-color: ${border} !important;
        }

        [class*="border-gray-700"], [class*="border-gray-600"] {
            border-color: ${border} !important;
        }

        [class*="border-gray-800"] {
            border-color: ${border} !important;
        }

        /* ===== NAVIGATION DROPDOWN ===== */
        .nav-dropdown-menu {
            background-color: ${navDropdownBg} !important;
            border-color: ${navDropdownBorder} !important;
        }

        .nav-dropdown-menu a {
            color: ${navLinkColor} !important;
        }

        .nav-dropdown-menu a:hover {
            background-color: ${navActiveBg} !important;
            color: ${navLinkHover} !important;
        }

        .nav-dropdown-menu a[class*="bg-purple-800"],
        .nav-dropdown-menu a[class*="text-white"] {
            background-color: ${navActiveBg} !important;
            color: ${navActiveColor} !important;
        }

        /* ===== PROGRESS BARS ===== */
        [class*="bg-gray-"][class*="rounded-full"] {
            background-color: ${progressBg} !important;
        }

        [class*="bg-blue-500"][class*="rounded-full"],
        [class*="bg-purple-500"][class*="rounded-full"],
        [class*="bg-blue-600"][class*="rounded-full"] {
            background-color: ${progressFill} !important;
        }

        [class*="bg-red-500"][class*="rounded-full"],
        [class*="bg-red-600"][class*="rounded-full"] {
            background-color: ${error} !important;
        }

        [class*="bg-yellow-500"][class*="rounded-full"],
        [class*="bg-yellow-600"][class*="rounded-full"] {
            background-color: ${warning} !important;
        }

        [class*="bg-green-500"][class*="rounded-full"],
        [class*="bg-green-600"][class*="rounded-full"] {
            background-color: ${success} !important;
        }

        /* ===== STATUS BADGES ===== */
        .status-running, [class*="status-running"] { color: ${statusRunning} !important; }
        .status-exited, .status-stopped, [class*="status-exited"], [class*="status-stopped"] { color: ${statusExited} !important; }
        .status-paused, [class*="status-paused"] { color: ${statusPaused} !important; }
        .status-restarting, [class*="status-restarting"] { color: ${statusRestarting} !important; }
        .status-created, [class*="status-created"] { color: ${statusCreated} !important; }
        .status-removing, [class*="status-removing"] { color: ${statusRemoving} !important; }
        .status-dead, [class*="status-dead"] { color: ${statusDead} !important; }
        .status-healthy { color: ${statusRunning} !important; }
        .status-unhealthy { color: ${statusExited} !important; }

        /* ===== TOGGLE SWITCHES ===== */
        input[type="checkbox"][role="switch"]:not(:checked),
        .toggle-switch:not(.active),
        [class*="peer"]:not(:checked) ~ [class*="bg-gray"] {
            background-color: ${toggleOff} !important;
        }

        input[type="checkbox"][role="switch"]:checked,
        .toggle-switch.active,
        [class*="peer"]:checked ~ [class*="peer-checked"] {
            background-color: ${toggleOn} !important;
        }

        /* ===== MODALS ===== */
        [class*="fixed"][class*="inset-0"][class*="bg-black"], [class*="fixed"][class*="inset-0"][class*="bg-opacity"] {
            background-color: ${modalBackdrop} !important;
        }

        .modal-content, [class*="bg-gray-800"][class*="rounded-lg"][class*="shadow"] {
            background-color: ${modalBg} !important;
            border-color: ${modalBorder} !important;
        }

        /* ===== TOASTS ===== */
        .toast-success {
            background-color: ${toastSuccessBg} !important;
            border-color: ${toastSuccessBorder} !important;
            color: ${toastText} !important;
        }
        .toast-error {
            background-color: ${toastErrorBg} !important;
            border-color: ${toastErrorBorder} !important;
            color: ${toastText} !important;
        }
        .toast-warning {
            background-color: ${toastWarningBg} !important;
            border-color: ${toastWarningBorder} !important;
            color: ${toastText} !important;
        }
        .toast-info {
            background-color: ${toastInfoBg} !important;
            border-color: ${toastInfoBorder} !important;
            color: ${toastText} !important;
        }

        /* Fallback overrides for Tailwind toast classes */
        #toast-container [class*="bg-green-600"] {
            background-color: ${toastSuccessBg} !important;
        }
        #toast-container [class*="border-green-500"] {
            border-color: ${toastSuccessBorder} !important;
        }
        #toast-container [class*="bg-red-600"] {
            background-color: ${toastErrorBg} !important;
        }
        #toast-container [class*="border-red-500"] {
            border-color: ${toastErrorBorder} !important;
        }
        #toast-container [class*="bg-yellow-600"] {
            background-color: ${toastWarningBg} !important;
        }
        #toast-container [class*="border-yellow-500"] {
            border-color: ${toastWarningBorder} !important;
        }
        #toast-container [class*="bg-blue-600"] {
            background-color: ${toastInfoBg} !important;
        }
        #toast-container [class*="border-blue-500"] {
            border-color: ${toastInfoBorder} !important;
        }

        /* ===== FORMS & INPUTS ===== */
        input[type="text"], input[type="password"], input[type="email"],
        input[type="number"], input[type="search"], input[type="url"],
        textarea, select {
            background-color: ${inputBackground} !important;
            border-color: ${inputBorder} !important;
            color: ${textPrimary} !important;
            border-radius: ${buttonBorderRadius} !important;
        }

        input:focus, textarea:focus, select:focus {
            border-color: ${inputFocusBorder} !important;
            box-shadow: 0 0 0 2px ${ring}33 !important;
            outline: none !important;
        }

        /* ===== CODE BLOCKS ===== */
        code, pre, .CodeMirror, [class*="cm-editor"] {
            background-color: ${codeBg} !important;
            border-color: ${codeBorder} !important;
            ${typography.font_mono ? `font-family: ${typography.font_mono} !important;` : ''}
        }

        pre {
            border: 1px solid ${codeBorder} !important;
            border-radius: ${cardBorderRadius} !important;
        }

        /* ===== LOADING SPINNERS ===== */
        .animate-spin {
            color: ${spinnerColor} !important;
        }

        /* ===== SVG ICON COLORS ===== */
        .service-card svg circle {
            fill: ${isFlat ? 'none' : primary} !important;
            stroke: ${isFlat ? borderLight : accent} !important;
        }

        .service-card svg path {
            stroke: ${isFlat ? textMuted : accentLight} !important;
        }

        .service-card svg rect {
            stroke: ${isFlat ? borderLight : accent} !important;
        }

        /* ===== HEADINGS ===== */
        h1, h2, h3, h4, h5, h6 {
            ${typography.heading_weight ? `font-weight: ${typography.heading_weight} !important;` : ''}
        }

        /* ===== SCROLLBAR (for modern theme) ===== */
        ${isFlat ? `
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: ${bg};
        }
        ::-webkit-scrollbar-thumb {
            background: ${bgTertiary};
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: ${borderLight};
        }
        ` : ''}

        /* ===== TABLES ===== */
        table {
            border-color: ${border} !important;
        }
        th {
            background-color: ${bgTertiary} !important;
            color: ${textPrimary} !important;
            border-color: ${border} !important;
        }
        td {
            border-color: ${border} !important;
        }
        tr:hover td {
            background-color: ${bgTertiary}66 !important;
        }

        /* ===== LINKS ===== */
        a:not(.nav-link):not(.nav-dropdown-menu a) {
            color: ${primaryLight};
        }
        a:not(.nav-link):not(.nav-dropdown-menu a):hover {
            color: ${primary};
        }

        /* ===== DIVIDERS ===== */
        hr, [class*="divide-"] > * + * {
            border-color: ${border} !important;
        }

        /* ===== FOCUS RINGS ===== */
        [class*="focus:ring"] {
            --tw-ring-color: ${ring} !important;
        }

        /* ===== PLACEHOLDER TEXT ===== */
        ::placeholder {
            color: ${textMuted} !important;
        }
    `;

    styleElement.textContent = css;
}

// Helper function to get theme gradients
function getThemeGradients() {
    if (currentTheme && currentTheme.gradients && currentTheme.gradients.card_options) {
        return currentTheme.gradients.card_options;
    }
    // Default gradients
    return [
        'from-purple-800 to-indigo-900',
        'from-indigo-800 to-purple-900',
        'from-blue-800 to-purple-900',
        'from-purple-900 to-blue-800',
        'from-indigo-900 to-blue-900',
        'from-blue-900 to-indigo-900'
    ];
}

// Helper function to get current theme colors (for generating dynamic SVGs if needed)
function getThemeColors() {
    if (currentTheme && currentTheme.colors) {
        return currentTheme.colors;
    }
    return {
        primary: '#5f4b8b',
        accent: '#8a6cbd',
        accent_light: '#c9b6e6'
    };
}

// Helper function to get component-level config
function getThemeComponents() {
    if (currentTheme && currentTheme.components) {
        return currentTheme.components;
    }
    return {};
}

// Export for use in other scripts
window.ThemeLoader = {
    loadTheme,
    getThemeGradients,
    getThemeColors,
    getThemeComponents,
    getCurrentTheme: () => currentTheme
};

// Auto-load theme on DOMContentLoaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadTheme);
} else {
    loadTheme();
}
