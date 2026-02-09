// Places I've Ate Map URL
const foodUrl = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ8PYlhZJ6W-p4IJV4rDACwrBENCbrMBQaH2SVtGDnWW24vwfEgXv50UET6sJxgDl39Ox-GJmiukfj3/pub?output=csv"

// Places I've Ate Map
const foodmap = L.map('foodmap', {
    maxBounds: [[-90, -180], [90, 180]], // restricts view to one world
    maxBoundsViscosity: 1.0,
    minZoom: 2,
}).setView([34.003564514142624, -118.32031826962323], 10); // (1)!


// Add Marker Function

function addMarker(data, target_map) {
    if (target_map === 3) {
    const redPinIcon = L.icon({
      iconUrl: "../images/80b2b82a0488e38c372a3ff50421a7af.png", // your local image path
      iconSize: [30, 30],   // adjust as needed
      iconAnchor: [16, 30], // bottom center of the pin
      popupAnchor: [0, -45] // popup appears above the pin
    });

    L.marker([data.LAT, data.LON], { icon: redPinIcon })
      .addTo(foodmap)
      .bindPopup(`<h2>${data.Name}</h2>`);
    } else {
        L.marker([data.lat, data.lng])
        .addTo(map)
        .bindPopup(`<h2>${data.city}</h2> <h3>${data.description}</h3>`);
    }
}


// Loading in the data
function loadData(url, tgt_map){
    Papa.parse(url, {
        header: true,
        download: true,
        complete: results => processData(results,tgt_map)
    })
}

let colorMap = {}; // store colors per route

function addGreatCircleSegment(from, to, options) {
    // Generate great-circle arc using leaflet-arc
    let arcLine = L.Polyline.Arc(from, to, {
        vertices: 200,
        ...options
    });

    // Extract coords
    let coords = arcLine.getLatLngs();

    // Normalize longitudes into [-180, 180]
    coords = coords.map(pt => {
        let lng = pt.lng;
        if (lng > 180) lng -= 360;
        if (lng < -180) lng += 360;
        return L.latLng(pt.lat, lng);
    });

    // Split at the dateline
    let splitCoords = [[]];
    let prev = coords[0];
    splitCoords[0].push(prev);

    for (let i = 1; i < coords.length; i++) {
        let curr = coords[i];

        // If longitude "jumps" across the globe, break the line
        if (Math.abs(curr.lng - prev.lng) > 180) {
            splitCoords.push([curr]);
        } else {
            splitCoords[splitCoords.length - 1].push(curr);
        }
        prev = curr;
    }

    // Add each clean segment
    splitCoords.forEach(seg => {
        if (seg.length > 1) {
            L.polyline(seg, {
                ...options,
                noClip: true
            }).addTo(map);
        }
    });
}

function processData(results, tgt_map){
    let routes = {};
    let seenCities = {};

    if (tgt_map == 3){
        results.data.forEach(data => {
        addMarker(data, 3)
    }
        )}

    else{
}
}

// we will put this comment to remember to call our function later!
loadData(foodUrl, 3)

// Leaflet tile layer, i.e. the base map

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    noWrap: true,
    bounds: [[-90, -180], [90, 180]],
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(foodmap);

//JavaScript let variable declaration to create a marker
