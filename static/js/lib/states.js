export function clearElement(node) {
    if (!node) {
        return;
    }

    while (node.firstChild) {
        node.removeChild(node.firstChild);
    }
}

function addOptionalSubtitle(wrapper, subtitle, subtitleClass) {
    if (!subtitle) {
        return;
    }

    const subtitleEl = document.createElement('p');
    subtitleEl.className = subtitleClass;
    subtitleEl.textContent = subtitle;
    wrapper.appendChild(subtitleEl);
}

function addOptionalAction(wrapper, action, actionClass) {
    if (!action?.href || !action?.label) {
        return;
    }

    const link = document.createElement('a');
    link.className = actionClass;
    link.href = action.href;
    link.textContent = action.label;
    wrapper.appendChild(link);
}

export function createLoadingState({
    message = 'Loading...',
    containerClass = 'col-span-full text-center py-10',
    messageClass = 'text-gray-400',
} = {}) {
    const wrapper = document.createElement('div');
    wrapper.className = containerClass;

    const messageEl = document.createElement('p');
    messageEl.className = messageClass;
    messageEl.textContent = message;
    wrapper.appendChild(messageEl);

    return wrapper;
}

export function createEmptyState({
    title = 'No data found.',
    subtitle = '',
    action = null,
    containerClass = 'col-span-full text-center py-10',
    titleClass = 'mt-4 text-xl',
    subtitleClass = 'text-gray-400 mt-2',
    actionClass = 'text-blue-300 underline hover:text-blue-200 mt-2 inline-block',
} = {}) {
    const wrapper = document.createElement('div');
    wrapper.className = containerClass;

    const titleEl = document.createElement('p');
    titleEl.className = titleClass;
    titleEl.textContent = title;
    wrapper.appendChild(titleEl);

    addOptionalSubtitle(wrapper, subtitle, subtitleClass);
    addOptionalAction(wrapper, action, actionClass);
    return wrapper;
}

export function createErrorState({
    title = 'Something went wrong.',
    subtitle = '',
    action = null,
    containerClass = 'col-span-full text-center py-10',
    titleClass = 'text-red-400',
    subtitleClass = 'text-gray-400 mt-2',
    actionClass = 'text-blue-300 underline hover:text-blue-200 mt-2 inline-block',
} = {}) {
    const wrapper = document.createElement('div');
    wrapper.className = containerClass;

    const titleEl = document.createElement('p');
    titleEl.className = titleClass;
    titleEl.textContent = title;
    wrapper.appendChild(titleEl);

    addOptionalSubtitle(wrapper, subtitle, subtitleClass);
    addOptionalAction(wrapper, action, actionClass);
    return wrapper;
}
