from pyscript import document
from pyodide.http import pyfetch
import asyncio
import json
import math

# No more preloaded developer key!
OPENROUTER_KEY = ""

print("=================================")
print("FlightDeck AI started successfully")
print("PyScript loaded")
print("=================================")

# Store globally
generated_airports = {}
selected_origin = ""
selected_aircraft_type = ""

aircraft_specs = {
    "C172": {"name": "Cessna 172 Skyhawk", "speed": 110},
    "SR22": {"name": "Cirrus SR22", "speed": 180},
    "TBM9": {"name": "Daher TBM 930", "speed": 320},
    "C700": {"name": "Cessna Citation Longitude", "speed": 480}
}

# Math: Haversine formula to calculate absolute distance in Nautical Miles
def calculate_distance_nm(lat1, lon1, lat2, lon2):
    R = 3440.065  # Earth radius in Nautical Miles
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

async def progress(percent, text):
    print(f"Progress {percent}% - {text}")
    document.querySelector("#progressBar").style.width = f"{percent}%"
    document.querySelector("#statusText").innerHTML = text
    await asyncio.sleep(.3)

async def ask_ai(prompt, flight_time, origin, aircraft_code):
    await progress(25, "Asking AI dispatcher...")
    print("Preparing OpenRouter request")

    # Fetch key dynamically from the Settings DOM element
    custom_key_element = document.querySelector("#apiKeyInput")
    active_key = custom_key_element.value.strip() if custom_key_element else ""
    
    # Strictly require a user key to be entered
    if not active_key:
        raise Exception("API key missing! Click the '⚙️ Settings' button in the top right, paste your OpenRouter API key, and try again.")

    aircraft = aircraft_specs.get(aircraft_code, {"name": "Cessna 172 Skyhawk", "speed": 110})
    cruise_speed = aircraft["speed"]
    aircraft_name = aircraft["name"]
    max_distance = float(flight_time) * cruise_speed

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {active_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://flightdeckai.com",
        "X-Title": "FlightDeck AI"
    }

    system_prompt = """
You are an expert flight dispatcher. Create realistic IFR flight recommendations based on real-world geography.

CRITICAL DISTANCE LAWS:
1. The pilot is flying a AIRCRAFT_NAME with an average cruise speed of CRUISE_SPEED knots.
2. In FLIGHT_TIME hours, the plane can cover approximately MAX_DISTANCE nautical miles.
3. Recommend 2 to 3 real-world, valid destination airport codes that are matching this distance within +/- 20% range from the origin. 
   - DO NOT recommend destination airports that are geographically impossible for this duration and speed.
   - Do your best to estimate real-world distances. Boston to Florida is over 800 miles and is strictly illegal for a Cessna 172 on a short duration!
   - If it says a time, strictly dont go over, only go under or exactly the same.

You MUST respond with a JSON object matching this exact format:
{
  "origin_lat": 42.3643,
  "origin_lon": -71.0052,
  "briefing": "A short global briefing overview highlighting how the AIRCRAFT_NAME handles this route.",
  "airports": [
    {
      "code": "KLAX",
      "name": "Los Angeles International",
      "lat": 33.9416,
      "lon": -118.4085,
      "route_details": "Brief summary of why this specific route was chosen."
    }
  ]
}
"""

    system_prompt = system_prompt.replace("AIRCRAFT_NAME", aircraft_name) \
                                 .replace("CRUISE_SPEED", str(cruise_speed)) \
                                 .replace("FLIGHT_TIME", str(flight_time)) \
                                 .replace("MAX_DISTANCE", f"{max_distance:.0f}")

    data = {
        "model": "openai/gpt-4o-mini",
        "response_format": { "type": "json_object" },
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": f"Origin Airport ICAO: {origin}\nPilot Request details: {prompt}\nDesired Flight Length: {flight_time} hours\nSelect 2 to 3 destinations. Provide exact coordinates for the origin and all destinations."
            }
        ]
    }

    try:
        response = await pyfetch(
            url,
            method="POST",
            headers=headers,
            body=json.dumps(data)
        )

        if response.status != 200:
            error_text = await response.text()
            return {"error": f"OpenRouter API Error (Status {response.status})"}

        result = await response.json()
        answer_string = result["choices"][0]["message"]["content"]
        return json.loads(answer_string)

    except Exception as e:
        return {"error": str(e)}

async def get_weather(lat, lon):
    headers = { "User-Agent": "(FlightDeckAI, contact@flightdeckai.com)" }
    try:
        point = await pyfetch(
            f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}",
            method="GET",
            headers=headers
        )
        if point.status != 200:
            return None
            
        point_data = await point.json()
        forecast = await pyfetch(
            point_data["properties"]["forecast"],
            method="GET",
            headers=headers
        )
        forecast_data = await forecast.json()
        p = forecast_data["properties"]["periods"][0]
        return {
            "temp": p["temperature"],
            "unit": p["temperatureUnit"],
            "wind": p["windSpeed"],
            "windDir": p["windDirection"],
            "conditions": p["shortForecast"]
        }
    except Exception as e:
        print(f"NWS Weather bypass active: {e}")
        return None

async def select_destination(code):
    global generated_airports, selected_origin, selected_aircraft_type
    
    if code not in generated_airports:
        return
        
    airport = generated_airports[code]
    details_div = document.querySelector("#airportDetails")
    details_div.innerHTML = "<p class='text-muted'>📡 Contacting National Weather Service... Please wait.</p>"
    
    w = await get_weather(airport["lat"], airport["lon"])
    
    weather_html = ""
    if w:
        weather_html = """
        <div class="alert mt-3 border d-flex align-items-center gap-3" style="background-color: var(--btn-unselected-bg); border-color: var(--border-color) !important;">
            <div style="font-size: 2rem;">🌦️</div>
            <div>
                <strong class="text-uppercase" style="color: var(--neon-blue); font-size: 0.8rem; letter-spacing: 0.05em; display: block;">Live Destination Forecast</strong>
                <span class="fs-5 fw-bold">TEMP_VAL°UNIT_VAL</span> | 
                <span>Wind: WIND_DIR_VAL at WIND_VAL</span><br>
                <span class="text-muted small">Current conditions: COND_VAL</span>
            </div>
        </div>
        """.replace("TEMP_VAL", str(w['temp'])) \
           .replace("UNIT_VAL", str(w['unit'])) \
           .replace("WIND_DIR_VAL", str(w['windDir'])) \
           .replace("WIND_VAL", str(w['wind'])) \
           .replace("COND_VAL", str(w['conditions']))
    else:
        weather_html = """
        <div class="alert mt-3 border d-flex align-items-center gap-3" style="background-color: var(--btn-unselected-bg); border-color: var(--border-color) !important; opacity: 0.85;">
            <div style="font-size: 2rem;">🌎</div>
            <div>
                <strong class="text-uppercase text-warning" style="font-size: 0.8rem; letter-spacing: 0.05em; display: block;">Local Weather Forecast</strong>
                <span class="small text-muted">Weather feed only available within US territories. Check real-time METAR/TAF below for dynamic international reports.</span>
            </div>
        </div>
        """

    simbrief_url = f"https://dispatch.simbrief.com/options/new?orig={selected_origin}&dest={code}&type={selected_aircraft_type}"
    metar_url = f"https://metar-taf.com/{code}"
    chartfox_url = f"https://chartfox.org/{code}"

    card_template = """
    <div class="card border-primary">
        <div class="card-header bg-transparent border-bottom d-flex justify-content-between align-items-center py-3" style="border-color: var(--border-color) !important;">
            <h4 class="mb-0 fw-bold" style="color: var(--neon-blue);">CODE_VAL - NAME_VAL</h4>
            <span class="badge" style="background-color: var(--btn-unselected-bg); color: var(--text-muted); border: 1px solid var(--border-color);">LAT_VAL, LON_VAL</span>
        </div>
        <div class="card-body py-4">
            <p><strong>Calculated Distance:</strong> <span class="badge" style="background-color: var(--btn-unselected-bg); color: var(--neon-blue); border: 1px solid var(--border-color);">DIST_VAL NM</span></p>
            <p class="card-text text-muted mb-4"><strong>Dispatcher Route Notes:</strong> DETAIL_VAL</p>
            
            WEATHER_HTML_VAL
            
            <div class="mt-4 pt-3 d-flex flex-wrap gap-2 border-top" style="border-color: var(--border-color) !important;">
                <a target="_blank" href="CHARTFOX_VAL" class="btn btn-outline-primary py-2 px-3">
                     🗺️ Open Charts (ChartFox)
                </a>
                <a target="_blank" href="SIMBRIEF_VAL" class="btn btn-outline-primary py-2 px-3">
                     ✈️ Dispatch on SimBrief
                </a>
                <a target="_blank" href="METAR_VAL" class="btn btn-outline-primary py-2 px-3">
                     📡 Live METAR / TAF
                </a>
            </div>
        </div>
    </div>
    """

    card_html = card_template.replace("CODE_VAL", airport['code']) \
                             .replace("NAME_VAL", airport['name']) \
                             .replace("LAT_VAL", f"{airport['lat']:.4f}") \
                             .replace("LON_VAL", f"{airport['lon']:.4f}") \
                             .replace("DIST_VAL", f"{airport['calculated_distance']:.1f}") \
                             .replace("DETAIL_VAL", airport['route_details']) \
                             .replace("WEATHER_HTML_VAL", weather_html) \
                             .replace("CHARTFOX_VAL", chartfox_url) \
                             .replace("SIMBRIEF_VAL", simbrief_url) \
                             .replace("METAR_VAL", metar_url)

    details_div.innerHTML = card_html

async def generate_flight(event):
    global generated_airports, selected_origin, selected_aircraft_type
    
    print("Generate button clicked")
    button = document.querySelector("#generateButton")
    button.disabled = True
    document.querySelector("#progressArea").style.display = "block"
    document.querySelector("#output").innerHTML = ""

    request = document.querySelector("#request").value
    time = document.querySelector("#flightRange").value
    origin_input = document.querySelector("#origin")
    aircraft_input = document.querySelector("#aircraft")

    if origin_input is None or aircraft_input is None:
        button.disabled = False
        return
        
    selected_origin = origin_input.value.upper().strip()
    selected_aircraft_type = aircraft_input.value

    aircraft = aircraft_specs.get(selected_aircraft_type, {"speed": 110})
    max_allowed_distance = float(time) * aircraft["speed"]

    await progress(10, "Analyzing requested route constraints...")

    try:
        response = await ask_ai(request, time, selected_origin, selected_aircraft_type)

        if "error" in response:
            raise Exception(response["error"])

        await progress(80, "Verifying mathematical distance of options...")

        generated_airports = {}
        options_html = ""
        warnings_html = ""
        
        orig_lat = response.get("origin_lat", 0.0)
        orig_lon = response.get("origin_lon", 0.0)

        for airport in response.get("airports", []):
            code = airport["code"].upper()
            dest_lat = airport.get("lat", 0.0)
            dest_lon = airport.get("lon", 0.0)
            
            dist_nm = calculate_distance_nm(orig_lat, orig_lon, dest_lat, dest_lon)
            airport["calculated_distance"] = dist_nm
            
            if dist_nm > (max_allowed_distance * 1.25):
                print(f"REJECTED: {code} is {dist_nm:.1f} NM away. Limit is {max_allowed_distance} NM.")
                warnings_html += f"""
                <div class="alert alert-warning py-2 mb-1" style="font-size:0.85rem;">
                    ⚠️ <strong>Filtered out {code}</strong>: AI suggested a distance of {dist_nm:.0f} NM, which exceeds your {aircraft['speed']} kts aircraft limit ({max_allowed_distance:.0f} NM max for {time} hours).
                </div>
                """
                continue
                
            generated_airports[code] = airport
            
            option_item = """
            <button class="btn btn-outline-primary mb-2 text-start d-flex justify-content-between align-items-center w-100 py-3" 
                    onclick="select_destination('CODE_VAL')">
                <span><strong>CODE_VAL</strong> - NAME_VAL (<small>DIST_VAL NM</small>)</span>
                <span class="badge rounded-pill" style="background-color: var(--neon-blue); color: #fff;">Select</span>
            </button>
            """
            options_html += option_item.replace("CODE_VAL", code) \
                                       .replace("NAME_VAL", airport['name']) \
                                       .replace("DIST_VAL", f"{dist_nm:.0f}")

        await progress(100, "Flight options dispatched!")

        if not options_html:
            options_html = """
            <div class="alert alert-danger">
                No matching airports found within flight parameters. The AI's suggested routes were too far for this aircraft speed. Please try again!
            </div>
            """

        output_template = """
        <div class="card mb-4">
            <div class="card-body p-4">
                <h3 class="fw-bold mb-3" style="color: var(--neon-blue);">Dispatcher General Briefing</h3>
                <p class="text-muted">BRIEFING_VAL</p>
                WARNINGS_PLACEHOLDER
            </div>
        </div>
        
        <div class="row g-4">
            <div class="col-md-5">
                <h4 class="fw-bold mb-1">Recommended Options</h4>
                <p class="text-muted small mb-3">Select an airport option to load charts & dynamic forecast:</p>
                <div class="d-flex flex-column">
                    OPTIONS_VAL
                </div>
                
                <button class="btn btn-outline-secondary mt-3 w-100 d-flex align-items-center justify-content-center gap-2 py-2" 
                        onclick="generate_flight(null)">
                    <span>🔄</span> Refresh Recommendations
                </button>
            </div>
            <div class="col-md-7" id="airportDetails">
                <div class="card bg-light h-100 d-flex align-items-center justify-content-center p-4 text-center border-0" style="background-color: var(--card-inner-bg) !important; border: 1px dashed var(--border-color) !important;">
                    <p class="text-muted my-5">Select a destination on the left to review local forecast charts, METAR feeds, and dispatch documentation.</p>
                </div>
            </div>
        </div>
        """
        
        final_html = output_template.replace("BRIEFING_VAL", response.get('briefing', '')) \
                                    .replace("WARNINGS_PLACEHOLDER", warnings_html) \
                                    .replace("OPTIONS_VAL", options_html)

        document.querySelector("#output").innerHTML = final_html

    except Exception as e:
        print("MAIN ERROR:", e)
        error_template = """
        <div class="card border-danger">
            <div class="card-body text-danger p-4">
                <h3>Error Dispatching Route</h3>
                <p>ERROR_VAL</p>
            </div>
        </div>
        """
        document.querySelector("#output").innerHTML = error_template.replace("ERROR_VAL", str(e))
        
    button.disabled = False

# Export python functions to JS global scope
from js import window
window.select_destination = select_destination
window.generate_flight = generate_flight
