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
            text_primary: "#dbeafe",
            text_secondary: "#93c5fd"
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
            text_shadow: "2px 2px 4px rgba(0, 0, 0, 0.5)"
        }
    };
}

function applyTheme(theme) {
    // Update page title
    const titleElement = document.querySelector('title');
    if (titleElement && theme.title) {
        titleElement.textContent = theme.title;
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

    // Create or update dynamic style element
    let styleElement = document.getElementById('dynamic-theme-styles');
    if (!styleElement) {
        styleElement = document.createElement('style');
        styleElement.id = 'dynamic-theme-styles';
        document.head.appendChild(styleElement);
    }

    // Generate CSS with theme colors
    const css = `
        :root {
            --theme-primary: ${colors.primary || '#5f4b8b'};
            --theme-primary-light: ${colors.primary_light || '#6f58a3'};
            --theme-primary-dark: ${colors.primary_dark || '#372b53'};
            --theme-accent: ${colors.accent || '#8a6cbd'};
            --theme-accent-light: ${colors.accent_light || '#c9b6e6'};
            --theme-background: ${colors.background || '#111827'};
            --theme-background-secondary: ${colors.background_secondary || '#1f2937'};
            --theme-text-primary: ${colors.text_primary || '#dbeafe'};
            --theme-text-secondary: ${colors.text_secondary || '#93c5fd'};
        }

        /* Update service card borders with theme colors */
        .service-card {
            border-color: ${colors.primary}4D !important; /* 30% opacity */
        }

        .service-card:hover {
            box-shadow: ${effects.card_hover_glow || '0 0 30px rgba(139, 92, 246, 0.5)'} !important;
            border-color: ${colors.accent}99 !important; /* 60% opacity */
        }

        /* Update Coraline/theme button styles */
        .coraline-button, .theme-button {
            background: linear-gradient(to bottom, ${colors.primary}, ${colors.primary_dark}) !important;
            border-color: ${colors.accent} !important;
        }

        .coraline-button:hover, .theme-button:hover {
            background: linear-gradient(to bottom, ${colors.primary_light}, ${colors.primary}) !important;
        }

        /* Update SVG icon colors dynamically */
        .service-card svg circle {
            fill: ${colors.primary} !important;
            stroke: ${colors.accent} !important;
        }

        .service-card svg path {
            stroke: ${colors.accent_light} !important;
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

// Export for use in other scripts
window.ThemeLoader = {
    loadTheme,
    getThemeGradients,
    getThemeColors,
    getCurrentTheme: () => currentTheme
};

// Auto-load theme on DOMContentLoaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadTheme);
} else {
    loadTheme();
}
