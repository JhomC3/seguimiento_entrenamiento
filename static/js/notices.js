// notices.js — owns: scheduling and display of .notice notifications.
// DOM owned: #notice-container, #editor-notice, .notice elements.
// Public API: scheduleNotices, flashEditorNotice.

export function scheduleNotices() {
    document.querySelectorAll('.notice:not(.scheduled)').forEach(function (el) {
        el.classList.add('scheduled');
        const delay = parseInt(el.dataset.dismiss || '3000', 10);
        setTimeout(function () {
            el.classList.add('hide');
            setTimeout(function () { el.remove(); }, 450);
        }, delay);
    });
}

export function flashEditorNotice(msg, type) {
    const box = document.getElementById('editor-notice');
    if (!box) return;
    const div = document.createElement('div');
    div.className = `notice ${type === 'error' ? 'notice-error' : 'notice-success'}`;
    div.dataset.dismiss = '2500';
    div.setAttribute('role', type === 'error' ? 'alert' : 'status');
    div.textContent = msg;
    box.appendChild(div);
    scheduleNotices();
}
