// Levels and axes: the print button prints the page (structure_overview.css fits the table to the page).
document.querySelectorAll('[data-print-page]').forEach(button => {
    window.inventoryActions?.enable(button);
    button.disabled = false;
    button.addEventListener('click', () => window.print());
});
