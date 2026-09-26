import os
import requests
import json
from shapely.geometry import shape

os.makedirs('data', exist_ok=True)

# 1. India States (Natural Earth 50m Admin 1)
states_url = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_1_states_provinces.geojson'
print('Fetching India states...')
r = requests.get(states_url, timeout=30)
data = r.json()
india_states = {
    'type': 'FeatureCollection',
    'features': [
        f for f in data['features']
        if f['properties'].get('admin') == 'India' or f['properties'].get('sov_a3') == 'IND'
    ]
}
states_path = os.path.join('data', 'india_states.geojson')
with open(states_path, 'w', encoding='utf-8') as f:
    json.dump(india_states, f)
print(f"Saved {len(india_states['features'])} states to {states_path} ({os.path.getsize(states_path)/1024:.1f} KB)")

# 2. Lakes in South Asia region (Natural Earth 10m Lakes)
lakes_url = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_lakes.geojson'
print('Fetching lakes...')
r = requests.get(lakes_url, timeout=30)
lakes_data = r.json()
bbox_polygon = shape({
    'type': 'Polygon',
    'coordinates': [[[65, 5], [100, 5], [100, 40], [65, 40], [65, 5]]]
})

region_lakes = {
    'type': 'FeatureCollection',
    'features': [
        f for f in lakes_data['features']
        if shape(f['geometry']).intersects(bbox_polygon)
    ]
}
lakes_path = os.path.join('data', 'regional_lakes.geojson')
with open(lakes_path, 'w', encoding='utf-8') as f:
    json.dump(region_lakes, f)
print(f"Saved {len(region_lakes['features'])} lakes to {lakes_path} ({os.path.getsize(lakes_path)/1024:.1f} KB)")
