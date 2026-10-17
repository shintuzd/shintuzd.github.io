// Small enhancements shared by every page.

// Add a subtle border under the sticky header once the page scrolls
const header = document.querySelector(".header");
if (header) {
    const onScroll = () => header.classList.toggle("is-scrolled", window.scrollY > 4);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
}

// Project filters: show only cards whose data-tags include the selected tag
const filters = document.querySelectorAll(".filter");
const cards = document.querySelectorAll(".cards .card");
filters.forEach(button => {
    button.addEventListener("click", () => {
        const tag = button.dataset.filter;
        filters.forEach(b => b.setAttribute("aria-pressed", String(b === button)));
        cards.forEach(card => {
            card.hidden = tag !== "all" && !card.dataset.tags.split(",").includes(tag);
        });
    });
});

// Keep the copyright year current
document.querySelectorAll("[data-year]").forEach(el => {
    el.textContent = new Date().getFullYear();
});
