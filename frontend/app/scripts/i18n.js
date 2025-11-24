let messages = {};

/**
 * loads a messages json for the given locale into memory
 * logs a console error if the fetch fails and leaves previous messages intact
 * @param {string} [locale="en"]
 * @returns {Promise<void>}
 */
async function loadMessages(locale = "en") {
    const res = await fetch(`/messages-${locale}.json`);
    if (!res.ok) {
        console.error("failed to load messages for locale ", locale);
        return;
    }
    messages = await res.json();
}

/**
 * looks up a translation key in memory
 * returns the provided fallback if given; returns the key itself if missing
 * @param {string} key
 * @param {string} [fallback]
 * @returns {string}
 */
function translate(key, fallback) {
    if (Object.prototype.hasOwnProperty.call(messages, key)) { return messages[key]; }
    if (fallback !== undefined) { return fallback; }
    return key;
}

/**
 * applies translations to elements under a root node based on data-i18n attributes
 * skips elements that have child nodes to avoid clobbering structured content
 * @param {ParentNode} [root=document]
 */
function applyTranslations(root = document) {
    const elements = root.querySelectorAll("[data-i18n]");
    elements.forEach((el) => {
        const key = el.getAttribute("data-i18n");
        if (!key) return;
        if (el.children.length > 0) return;
        const value = translate(key, el.textContent);
        el.textContent = value;
    });
}

export { loadMessages, translate, applyTranslations };
