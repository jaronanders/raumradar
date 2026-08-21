const pushButton = document.getElementById("push-notifications");

function base64ToUint8Array(value) {
    const padding = "=".repeat((4 - value.length % 4) % 4);
    const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(base64), (character) => character.charCodeAt(0));
}

async function getPushRegistration() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
        throw new Error("Dieser Browser unterstützt keine Push-Benachrichtigungen.");
    }
    return navigator.serviceWorker.ready;
}

async function updatePushButton() {
    try {
        const registration = await getPushRegistration();
        const subscription = await registration.pushManager.getSubscription();
        pushButton.hidden = false;
        pushButton.textContent = subscription
            ? "Benachrichtigungen deaktivieren"
            : "Benachrichtigungen aktivieren";
    } catch {
        pushButton.hidden = true;
    }
}

async function syncPushFavorites() {
    try {
        const registration = await getPushRegistration();
        const subscription = await registration.pushManager.getSubscription();
        if (!subscription) return;
        await fetch("/api/push/favorites", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                endpoint: subscription.endpoint,
                favoriteRooms: JSON.parse(localStorage.getItem("raumradar-favorite-rooms") || "[]"),
            }),
        });
    } catch {
        // Push setup remains usable if favorite synchronization is temporarily unavailable.
    }
}

async function togglePushNotifications() {
    pushButton.disabled = true;
    try {
        const registration = await getPushRegistration();
        const current = await registration.pushManager.getSubscription();
        if (current) {
            await fetch("/api/push/unsubscribe", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ endpoint: current.endpoint }),
            });
            await current.unsubscribe();
            return;
        }

        const keyResponse = await fetch("/api/push/vapid-public-key");
        const keyData = await keyResponse.json();
        if (!keyResponse.ok) throw new Error(keyData.error || "Push ist nicht verfügbar.");
        const permission = await Notification.requestPermission();
        if (permission !== "granted") throw new Error("Benachrichtigungen wurden nicht erlaubt.");

        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: base64ToUint8Array(keyData.publicKey),
        });
        const saveResponse = await fetch("/api/push/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(subscription.toJSON()),
        });
        if (!saveResponse.ok) throw new Error("Push-Abonnement konnte nicht gespeichert werden.");
    } catch (error) {
        window.alert(error.message);
    } finally {
        pushButton.disabled = false;
        updatePushButton();
    }
}

pushButton.addEventListener("click", togglePushNotifications);
window.addEventListener("raumradar:favorites-changed", syncPushFavorites);
updatePushButton();
syncPushFavorites();