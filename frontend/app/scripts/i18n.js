let messages = {};

async function loadMessages(locale = "en") {
  const res = await fetch(`/messages-${locale}.json`);
  if (!res.ok) {
    console.error("failed to load messages for locale ", locale);
    return;
  }
  messages = await res.json();
}

function translate(key, fallback) {
  if (Object.prototype.hasOwnProperty.call(messages, key)) { return messages[key]; }
  if (fallback !== undefined) { return fallback; }
  return key;
}

function applyTranslations(root = document) {
  const elements = root.querySelectorAll("[data-i18n]");
  elements.forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (!key) return;
    const value = translate(key, el.textContent);
    el.textContent = value;
  });
}

export { loadMessages, translate, applyTranslations };
