const nextLessons = JSON.parse(document.getElementById("next-lessons").textContent);
const favoriteKey = "raumradar-favorite-rooms";
const favoriteRooms = new Set(JSON.parse(localStorage.getItem(favoriteKey) || "[]"));
const details = document.getElementById("room-details");
const title = document.getElementById("room-details-title");
const text = document.getElementById("room-details-text");
const favoriteContainer = document.getElementById("favorite-rooms");
const loadingMessage = document.getElementById("loading-message");
const roomButtons = [...document.querySelectorAll(".room-button")];
const roomButtonsByName = new Map(roomButtons.map((button) => [button.dataset.room, button]));
const favoriteButtons = [...document.querySelectorAll(".favorite-button")];

function renderFavorites() {
    favoriteContainer.replaceChildren();
    const roomStatus = new Map(
        roomButtons.map((button) => [
            button.dataset.room,
            button.classList.contains("occupied") ? "Belegt" : "Frei"
        ])
    );
    const favorites = [...favoriteRooms].filter((room) => roomStatus.has(room));
    if (!favorites.length) {
        const empty = document.createElement("p");
        empty.className = "favorite-empty";
        empty.textContent = "Noch keine Favoriten markiert.";
        favoriteContainer.append(empty);
        return;
    }
    favorites.forEach((room) => {
        const shortcut = document.createElement("button");
        const status = roomStatus.get(room);
        shortcut.className = `favorite-chip ${status === "Belegt" ? "favorite-occupied" : "favorite-free"}`;
        shortcut.type = "button";
        shortcut.innerHTML = `<strong>★ ${room}</strong><small>${status}</small>`;
        shortcut.addEventListener("click", () => roomButtonsByName.get(room)?.click());
        favoriteContainer.append(shortcut);
    });
}

favoriteButtons.forEach((button) => {
    const room = button.dataset.room;
    const update = () => {
        const isFavorite = favoriteRooms.has(room);
        button.textContent = isFavorite ? "★" : "☆";
        button.classList.toggle("is-favorite", isFavorite);
        button.setAttribute(
            "aria-label",
            isFavorite ? `Raum ${room} aus Favoriten entfernen` : `Raum ${room} favorisieren`
        );
    };
    update();
    button.addEventListener("click", () => {
        favoriteRooms.has(room) ? favoriteRooms.delete(room) : favoriteRooms.add(room);
        localStorage.setItem(favoriteKey, JSON.stringify([...favoriteRooms]));
        window.dispatchEvent(new Event("raumradar:favorites-changed"));
        update();
        renderFavorites();
    });
});

roomButtons.forEach((button) => {
    button.addEventListener("click", () => {
        const room = button.dataset.room;
        const lesson = nextLessons[room];
        title.textContent = `Raum ${room}`;
        text.textContent = lesson
            ? `Nächster Unterricht: ${lesson.start}-${lesson.end} Uhr (${lesson.subject})`
            : "Heute findet hier kein weiterer Unterricht statt.";
        details.hidden = false;
        details.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
});

renderFavorites();
window.setTimeout(() => window.location.reload(), 120000);
window.addEventListener("beforeunload", () => { loadingMessage.hidden = false; });
