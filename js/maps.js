// Shared Leaflet maps for the About page and the full-page maps in /docs.
// Any element with data-map="food" or data-map="travel" is initialized automatically.
// Add data-embedded to a map that sits inside a page of text, so the mouse wheel scrolls the page instead of zooming
// (trackpad pinch still zooms the map).

// Places I've Eaten
const FOOD_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ8PYlhZJ6W-p4IJV4rDACwrBENCbrMBQaH2SVtGDnWW24vwfEgXv50UET6sJxgDl39Ox-GJmiukfj3/pub?output=csv";
// Places I've Been / Want to Go
const PLACES_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRkmSXxg8YWhtkeX7iiBcY-uYjHURNjBdMz9iNUGyUIekHd2Jfp1CqxVRbvwHt-uJZF0ecZWctmHCim/pub?gid=1065135092&single=true&output=csv";
const PLACES_GO_TO_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRkmSXxg8YWhtkeX7iiBcY-uYjHURNjBdMz9iNUGyUIekHd2Jfp1CqxVRbvwHt-uJZF0ecZWctmHCim/pub?gid=287701830&single=true&output=csv";

const FOOD_START_ZOOM = 10;

const ROUTE_COLORS = ["#e63946", "#1d4ed8", "#2a9d8f", "#f4a261", "#7b2cbf", "#8d5524", "#e76f9f"];

// Resolve image paths relative to this script so it works from / and /docs/
const SCRIPT_URL = document.currentScript.src;
const PIN_URL = new URL("../images/web/pin.png", SCRIPT_URL).href;

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
}

function toLatLng(lat, lng) {
    const la = parseFloat(lat);
    const ln = parseFloat(lng);
    return Number.isFinite(la) && Number.isFinite(ln) ? [la, ln] : null;
}

function baseMap(el, view, zoom, minZoom) {
    const map = L.map(el, {
        maxBounds: [[-90, -180], [90, 180]], // restricts view to one world
        maxBoundsViscosity: 1.0,
        minZoom: minZoom,
        scrollWheelZoom: !el.hasAttribute("data-embedded"),
    }).setView(view, zoom);

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        noWrap: true,
        bounds: [[-90, -180], [90, 180]],
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    // Embedded maps: trackpad pinch zooms the map (instead of the page) right away,
    // and clicking the map opts in to plain mouse-wheel zoom too
    if (el.hasAttribute("data-embedded")) {
        map.addHandler("pinchZoom", PinchWheelZoom);
        map.pinchZoom.enable();
        map.once("click", () => {
            map.pinchZoom.disable();
            map.scrollWheelZoom.enable();
        });
    }
    return map;
}

// Trackpad pinches arrive as wheel events with ctrlKey set. Zoom the map on those only,
// and let ordinary wheel/two-finger scrolling fall through to the page.
const PinchWheelZoom = L.Map.ScrollWheelZoom.extend({
    _onWheelScroll(e) {
        if (!e.ctrlKey) return;
        L.Map.ScrollWheelZoom.prototype._onWheelScroll.call(this, e);
    }
});

function loadCsv(url) {
    return new Promise((resolve, reject) => {
        Papa.parse(url, {
            header: true,
            download: true,
            skipEmptyLines: true,
            complete: results => resolve(results.data),
            error: reject,
        });
    });
}

function setStatus(el, text) {
    const status = document.querySelector(`[data-status-for="${el.id}"]`);
    if (status) status.textContent = text;
}

// --- Food map -------------------------------------------------------------

async function initFoodMap(el) {
    const map = baseMap(el, [34.0035, -118.3203], FOOD_START_ZOOM, 2);
    const pin = L.icon({
        iconUrl: PIN_URL,
        iconSize: [30, 30],
        iconAnchor: [15, 30], // bottom center of the pin
        popupAnchor: [0, -30]
    });

    // Cluster nearby pins so dense neighborhoods stay readable,
    // then show individual pins once zoomed in 4 levels from the starting view
    const layer = L.markerClusterGroup
        ? L.markerClusterGroup({ maxClusterRadius: 40, disableClusteringAtZoom: FOOD_START_ZOOM + 4 })
        : L.layerGroup();
    layer.addTo(map);

    try {
        const rows = await loadCsv(FOOD_URL);
        let count = 0;
        rows.forEach(row => {
            const coords = toLatLng(row.LAT, row.LON);
            if (!coords) return;
            L.marker(coords, { icon: pin, title: row.Name })
                .bindPopup(`<h2>${escapeHtml(row.Name)}</h2>`)
                .addTo(layer);
            count++;
        });
        setStatus(el, `${count.toLocaleString()} spots mapped (and counting).`);
    } catch (err) {
        console.error(err);
        setStatus(el, "The restaurant data couldn't be loaded right now. Please try again later.");
    }
}

// --- Travel map -----------------------------------------------------------

function addGreatCircleSegment(map, from, to, options) {
    // Generate great-circle arc using leaflet-arc
    const arcLine = L.Polyline.Arc(from, to, { vertices: 200, ...options });

    // Normalize longitudes into [-180, 180]
    const coords = arcLine.getLatLngs().map(pt => {
        let lng = pt.lng;
        if (lng > 180) lng -= 360;
        if (lng < -180) lng += 360;
        return L.latLng(pt.lat, lng);
    });

    // Split at the dateline: if longitude "jumps" across the globe, break the line
    const segments = [[coords[0]]];
    for (let i = 1; i < coords.length; i++) {
        if (Math.abs(coords[i].lng - coords[i - 1].lng) > 180) {
            segments.push([coords[i]]);
        } else {
            segments[segments.length - 1].push(coords[i]);
        }
    }

    segments.forEach(seg => {
        if (seg.length > 1) L.polyline(seg, { ...options, noClip: true }).addTo(map);
    });
}

function addLegend(map) {
    const legend = L.control({ position: "bottomright" });
    legend.onAdd = function () {
        const div = L.DomUtil.create("div", "info legend");
        div.innerHTML =
            "<strong>Legend</strong>" +
            `<div class="legend-item"><img src="https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png" class="marker-img" alt=""> <span>Where I've Been</span></div>` +
            '<div class="legend-item"><i class="legend-icon-want"></i> <span>Where I Want to Go</span></div>';
        return div;
    };
    legend.addTo(map);
}

async function initTravelMap(el) {
    const map = baseMap(el, [48.7425, -35.5685], el.hasAttribute("data-embedded") ? 2 : 3, 2);
    addLegend(map);

    const popup = row => `<h2>${escapeHtml(row.city)}</h2><h3>${escapeHtml(row.description)}</h3>`;

    try {
        const [visited, wishlist] = await Promise.all([loadCsv(PLACES_URL), loadCsv(PLACES_GO_TO_URL)]);

        // Places I want to go: small green circles
        wishlist.forEach(row => {
            const coords = toLatLng(row.lat, row.lng);
            if (!coords) return;
            L.circleMarker(coords, {
                radius: 5,
                fillColor: "#28a745",
                color: "#1e7e34",
                weight: 1,
                opacity: 1,
                fillOpacity: 0.5
            }).bindPopup(popup(row)).addTo(map);
        });

        // Places I've been: one marker per city, plus curved route lines
        const seenCities = new Set();
        const routes = {};
        visited.forEach(row => {
            const coords = toLatLng(row.lat, row.lng);
            if (!coords) return;

            if (!seenCities.has(row.city)) {
                L.marker(coords, { title: row.city }).bindPopup(popup(row)).addTo(map);
                seenCities.add(row.city);
            }
            if (row.route_id) {
                (routes[row.route_id] ||= []).push(coords);
            }
        });

        if (L.Polyline.Arc) {
            Object.values(routes).forEach((pts, i) => {
                const color = ROUTE_COLORS[i % ROUTE_COLORS.length];
                for (let j = 0; j < pts.length - 1; j++) {
                    addGreatCircleSegment(map, pts[j], pts[j + 1], { color, weight: 3, opacity: 0.8 });
                }
            });
        }

        setStatus(el, `${seenCities.size} places visited, ${wishlist.length} on the list.`);
    } catch (err) {
        console.error(err);
        setStatus(el, "The travel data couldn't be loaded right now. Please try again later.");
    }
}

document.querySelectorAll('[data-map="food"]').forEach(initFoodMap);
document.querySelectorAll('[data-map="travel"]').forEach(initTravelMap);
