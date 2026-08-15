// modal-dialog.js — native <dialog> management: showModal, close, origin focus
// restoration and nested-dialog restoration. No hand-rolled focus trap: the
// browser owns containment for modal dialogs.
// Public API: openDialog, closeDialog.

const openedDialogs = [];

export function openDialog(dialog) {
    if (!dialog || dialog.open) return;
    const origin = document.activeElement;
    openedDialogs.push({ dialog, origin });
    dialog.showModal();
    // Foco inicial: el primer elemento enfocable dentro del dialog.
    const first = dialog.querySelector(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (first) first.focus();
}

export function closeDialog(dialog) {
    if (!dialog || !dialog.open) return;
    dialog.close();
    const entry = openedDialogs.filter(function (e) { return e.dialog === dialog; }).pop();
    if (entry) {
        const idx = openedDialogs.indexOf(entry);
        openedDialogs.splice(idx, 1);
        // Restauración de foco: al trigger original, o al dialog que quedó
        // debajo (confirmación abierta dentro del popup), o al body.
        if (openedDialogs.length) {
            const below = openedDialogs[openedDialogs.length - 1];
            if (below.dialog && below.dialog.open) below.dialog.focus();
            else if (below.origin && below.origin.focus) below.origin.focus();
        } else if (entry.origin && entry.origin.focus) {
            entry.origin.focus();
        }
    }
}
