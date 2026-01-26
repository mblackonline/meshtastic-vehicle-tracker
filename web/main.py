import os
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import psycopg2
from psycopg2.extras import RealDictCursor


app = FastAPI()

# Get base directory
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Database configuration from environment
DB_CONFIG = {
    "host": os.environ["POSTGRES_HOST"],
    "port": int(os.environ["POSTGRES_PORT"]),
    "dbname": os.environ["POSTGRES_DB"],
    "user": os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
}


def get_db_connection():
    """Create a new database connection."""
    return psycopg2.connect(**DB_CONFIG)


@app.get("/api/buses")
async def get_buses() -> Dict[str, Any]:
    """
    Get latest position for each vehicle in GeoJSON format.
    Returns GeoJSON FeatureCollection for map display.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get latest position for each node_id
            query = """
                SELECT DISTINCT ON (node_id)
                    node_id,
                    lat,
                    lon,
                    ts_utc,
                    speed,
                    heading,
                    battery_v,
                    rssi,
                    snr
                FROM positions
                WHERE lat IS NOT NULL AND lon IS NOT NULL
                ORDER BY node_id, ts_utc DESC
            """
            cur.execute(query)
            rows = cur.fetchall()

            # Build GeoJSON FeatureCollection
            features = []
            for row in rows:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "vehicleId": row["node_id"],
                        "latitude": float(row["lat"]) if row["lat"] else None,
                        "longitude": float(row["lon"]) if row["lon"] else None,
                        "timestamp": row["ts_utc"].isoformat() if row["ts_utc"] else None,
                        "speed": float(row["speed"]) if row["speed"] else None,
                        "heading": float(row["heading"]) if row["heading"] else None,
                        "battery": float(row["battery_v"]) if row["battery_v"] else None,
                        "rssi": row["rssi"],
                        "snr": float(row["snr"]) if row["snr"] else None,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            float(row["lon"]) if row["lon"] else None,
                            float(row["lat"]) if row["lat"] else None,
                        ]
                    }
                })

            return {
                "type": "FeatureCollection",
                "features": features
            }
    finally:
        conn.close()


@app.get("/")
async def root():
    """Serve the map HTML page."""
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files for CSS, JS, and other assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
