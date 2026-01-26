var mapOptions = {
    container: 'map',
    style: {
        version: 8,
        sources: {
            osm: {
                type: 'raster',
                tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                tileSize: 256,
                attribution: '&copy; OpenStreetMap Contributors',
                maxzoom: 19
            }
        },
        layers: [
            {
                id: 'osm',
                type: 'raster',
                source: 'osm'
            }
        ]
    },
    center: [-98.5795, 39.8283], // Geographic center of continental US
    zoom: 4
};

// zoom out more if on mobile
if (window.innerWidth < 800) {
    mapOptions.zoom = 3;
    mapOptions.attributionControl = false;
}

var map = new maplibregl.Map(mapOptions);

if (window.innerWidth < 800) {
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
}

let currentMarkers = [];
let spiderMarkers = [];
let spiderOpenId = null;
let spiderOpenCluster = null;
let spiderHandlersAttached = false;
let activePopup = null;
let activeBusId = null;

const CLUSTER_DISTANCE_PX = 28;

function formatBusTime(bus) {
    const ts = bus.properties.timestamp;
    return ts ? new Date(ts).toLocaleTimeString() : 'Unknown time';
}

function formatBusSpeed(bus) {
    const speed = bus.properties.speed;
    if (speed === null || speed === undefined) return 'Speed: N/A';
    return `Speed: ${(speed * 2.237).toFixed(1)} mph`;
}

function formatSingleBusPopup(bus) {
    return `
        <strong>Vehicle ${bus.properties.vehicleId}</strong><br/>
        Last Update: ${formatBusTime(bus)}<br/>
        ${formatBusSpeed(bus)}
    `;
}

function clearMarkers(markers) {
    markers.forEach(marker => marker.remove());
    markers.length = 0;
}

function closeActivePopup() {
    if (!activePopup) return;
    activePopup.remove();
    activePopup = null;
    activeBusId = null;
}

function closeSpiderfy() {
    if (spiderMarkers.length === 0) return;
    clearMarkers(spiderMarkers);
    if (spiderOpenCluster && spiderOpenCluster.marker) {
        spiderOpenCluster.marker.getElement().style.display = '';
    }
    spiderOpenId = null;
    spiderOpenCluster = null;
}

function ensureSpiderfyHandlers() {
    if (spiderHandlersAttached) return;
    map.on('click', (event) => {
        const target = event.originalEvent && event.originalEvent.target;
        if (target && target.closest && (target.closest('.marker') || target.closest('.maplibregl-popup'))) return;
        closeActivePopup();
        closeSpiderfy();
    });
    map.on('movestart', closeSpiderfy);
    map.on('zoomstart', closeSpiderfy);
    map.on('dragstart', closeSpiderfy);
    spiderHandlersAttached = true;
}

function buildSpiderOffsets(count) {
    const offsets = [];
    const baseRadius = 40;
    const ringSpacing = 28;
    const minSpacing = 32;
    let remaining = count;
    let ring = 0;
    while (remaining > 0) {
        const radius = baseRadius + ring * ringSpacing;
        const capacity = Math.max(6, Math.floor((2 * Math.PI * radius) / minSpacing));
        const ringCount = Math.min(remaining, capacity);
        for (let i = 0; i < ringCount; i++) {
            const angle = (2 * Math.PI * i) / ringCount;
            offsets.push([Math.cos(angle) * radius, Math.sin(angle) * radius]);
        }
        remaining -= ringCount;
        ring += 1;
    }
    return offsets;
}

function openSpiderfy(cluster) {
    if (spiderOpenId === cluster.id) {
        closeSpiderfy();
        return;
    }

    closeSpiderfy();
    closeActivePopup();
    spiderOpenId = cluster.id;
    spiderOpenCluster = cluster;
    if (cluster.marker) {
        cluster.marker.getElement().style.display = 'none';
    }

    const centerPx = map.project(cluster.centerLngLat);
    const offsets = buildSpiderOffsets(cluster.buses.length);

    for (let i = 0; i < cluster.buses.length; i++) {
        const bus = cluster.buses[i];
        const offset = offsets[i];
        const lngLat = map.unproject([centerPx.x + offset[0], centerPx.y + offset[1]]);

        const el = document.createElement('div');
        el.className = "marker bus spider";
        el.innerHTML = `<div class="marker-inner bus-inner"><div class="marker-inner-text">${bus.properties.vehicleId}</div></div>`;

        const popup = new maplibregl.Popup({ offset: 25 }).setHTML(formatSingleBusPopup(bus));
        popup.on('close', () => {
            if (activePopup === popup) {
                activePopup = null;
                activeBusId = null;
            }
        });

        const marker = new maplibregl.Marker({ element: el })
            .setLngLat(lngLat)
            .addTo(map);

        el.addEventListener('click', (event) => {
            event.stopPropagation();
            if (activePopup && activePopup !== popup) activePopup.remove();
            activePopup = popup;
            activeBusId = bus.properties.vehicleId;
            popup.setLngLat(marker.getLngLat()).addTo(map);
        });

        spiderMarkers.push(marker);
    }
}

async function update_buses() {
    console.log("updating vehicles");
    if (spiderOpenId !== null || activePopup !== null) {
        return;
    }
    try {
        const res = await fetch('/api/buses');
        const data = await res.json();

        // Remove existing markers
        clearMarkers(currentMarkers);
        closeSpiderfy();
        ensureSpiderfyHandlers();

        // Add new markers
        const buses = data.features;
        const clusters = [];
        let clusterId = 0;

        for (let i = 0; i < buses.length; i++) {
            const bus = buses[i];
            const point = bus.geometry.coordinates;
            if (!point || point[0] === null || point[1] === null || point[0] === undefined || point[1] === undefined) continue;

            const lng = point[0];
            const lat = point[1];
            const projected = map.project([lng, lat]);

            let target = null;
            for (let j = 0; j < clusters.length; j++) {
                const cluster = clusters[j];
                const dx = projected.x - cluster.centerPx.x;
                const dy = projected.y - cluster.centerPx.y;
                if (Math.hypot(dx, dy) <= CLUSTER_DISTANCE_PX) {
                    target = cluster;
                    break;
                }
            }

            if (!target) {
                clusters.push({
                    id: clusterId++,
                    buses: [bus],
                    sumLon: lng,
                    sumLat: lat,
                    centerLngLat: [lng, lat],
                    centerPx: projected
                });
                continue;
            }

            target.buses.push(bus);
            target.sumLon += lng;
            target.sumLat += lat;
            const count = target.buses.length;
            target.centerLngLat = [target.sumLon / count, target.sumLat / count];
            target.centerPx = map.project(target.centerLngLat);
        }

        for (const cluster of clusters) {
            if (cluster.buses.length === 1) {
                const bus = cluster.buses[0];
                const point = bus.geometry.coordinates;

                const el = document.createElement('div');
                el.className = "marker bus";
                el.innerHTML = `<div class="marker-inner bus-inner"><div class="marker-inner-text">${bus.properties.vehicleId}</div></div>`;

                const popup = new maplibregl.Popup({ offset: 25 }).setHTML(formatSingleBusPopup(bus));
                popup.on('close', () => {
                    if (activePopup === popup) {
                        activePopup = null;
                        activeBusId = null;
                    }
                });

                const marker = new maplibregl.Marker({ element: el })
                    .setLngLat(point)
                    .addTo(map);

                el.addEventListener('click', (event) => {
                    event.stopPropagation();
                    if (activePopup && activePopup !== popup) activePopup.remove();
                    activePopup = popup;
                    activeBusId = bus.properties.vehicleId;
                    popup.setLngLat(marker.getLngLat()).addTo(map);
                });

                currentMarkers.push(marker);
                continue;
            }

            const el = document.createElement('div');
            el.className = "marker bus cluster";
            el.title = `${cluster.buses.length} vehicles here - click to expand`;
            el.innerHTML = `<div class="marker-inner bus-inner"><div class="marker-inner-text">${cluster.buses.length}</div></div>`;
            el.addEventListener('click', (event) => {
                event.stopPropagation();
                openSpiderfy(cluster);
            });

            const marker = new maplibregl.Marker({ element: el })
                .setLngLat(cluster.centerLngLat)
                .addTo(map);
            cluster.marker = marker;

            currentMarkers.push(marker);
        }

        console.log(`Updated ${buses.length} vehicles across ${clusters.length} locations`);
    } catch (error) {
        console.error('Error fetching vehicles:', error);
    }
}

// Initial update
update_buses();

// Update every 10 seconds
setInterval(update_buses, 10 * 1000);
