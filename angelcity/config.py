"""World layout constants and gameplay tuning. Units are meters, +X east, +Y north, +Z up.

The map is a compressed but geographically faithful miniature Los Angeles:
real freeway topology (10 / 110 / 101 / 405), real street names, real neighborhoods
in the right relative positions, and low-poly stand-ins for famous landmarks."""

# ---- world extents ----
BASIN_X0, BASIN_X1 = -1500.0, 1500.0
BASIN_Y0, BASIN_Y1 = -1200.0, 900.0
HILLS_Y1 = 1500.0          # Santa Monica Mtns / Hollywood Hills along the north
PORT_Y0 = -1400.0          # San Pedro / harbor strip along the south
WORLD_X0, WORLD_X1 = -2500.0, 1600.0
WORLD_Y0, WORLD_Y1 = -1700.0, 1560.0

# beach / ocean (west side, Santa Monica bay)
BEACH_X = -1400.0          # sand starts here, sloping down to the water
WATER_Z = -1.6
OCEAN_X = -1470.0          # approximate waterline
# LAX sits on a shelf that juts west (El Segundo), carving a notch in the coastline
LAX_Y0, LAX_Y1 = -1240.0, -760.0
LAX_COAST_X = -2140.0

# river channels (concrete, drivable)
CREEK_Y = -600.0           # "Ballona Creek": east-west, empties at the marina
RIVER_X = 1230.0           # "LA River": north-south past downtown to the harbor
RIVER_HALF_FLAT = 18.0
RIVER_HALF_TOP = 35.0
RIVER_DEPTH = 5.0

# elevated Santa Monica Fwy (10): east-west above the surface street at FREEWAY_Y
FREEWAY_Y = 120.0
FREEWAY_Z = 8.0
FREEWAY_HALF = 12.0
FREEWAY_X0, FREEWAY_X1 = -1380.0, 1440.0
# elevated Harbor Fwy (110): north-south above Figueroa, crosses OVER the 10
FWY110_X = 420.0
FWY110_Z = 13.0
FWY110_HALF = 11.0
FWY110_Y0, FWY110_Y1 = -1340.0, 640.0
# San Diego Fwy (405): at-grade widened avenue on the west side
FWY405_X = -1020.0
# Hollywood Fwy (101): at-grade ribbon running diagonally NW out of downtown
FWY101_PTS = [(620, 655), (300, 720), (-40, 780), (-360, 850), (-560, 940), (-700, 1060)]

# road grid
ROADS_V = [-1380.0 + i * 180.0 for i in range(16)]   # avenue centerlines (x)
ROADS_H = [-1140.0 + i * 180.0 for i in range(12)]   # street centerlines (y)
MAJOR_EVERY = 3
ROAD_HALF_MAJOR = 7.0
ROAD_HALF_MINOR = 5.0
SIDEWALK_W = 2.5
LANE_OFFSET = 3.0

# real street names, west→east for avenues, south→north for streets
NAMES_V = ["Ocean Ave", "Lincoln Blvd", "Sepulveda Blvd", "Centinela Ave", "La Cienega Blvd",
           "Fairfax Ave", "La Brea Ave", "Crenshaw Blvd", "Western Ave", "Normandie Ave",
           "Vermont Ave", "Figueroa St", "Main St", "Alameda St", "Soto St", "Atlantic Blvd"]
NAMES_H = ["Anaheim St", "Willow St", "Del Amo Blvd", "Ballona Creek", "Century Blvd",
           "Manchester Ave", "Florence Ave", "Slauson Ave", "Adams Blvd", "Pico Blvd",
           "Wilshire Blvd", "Sunset Blvd"]

# districts (axis-aligned boxes checked in order; first hit wins)
DOWNTOWN = (240, 960, 150, 640)
PARK = (-330, 30, 300, 640)
INDUSTRIAL_Y1 = -660
BEACHTOWN_X1 = -1050

# landmarks (positions roughly matching real relative geography; several sit on
# reserved city blocks — see City.reserved)
SIGN_POS = (-330.0, 1245.0)              # HOLLYWOOD sign on the south slope
OBSERVATORY = (350.0, 1180.0)            # Griffith-style observatory
BOWL_POS = (-470.0, 965.0)               # hillside amphitheater
PIER_Y = -300.0                          # Santa-Monica-style pier
MARINA_Y = -600.0                        # small-craft harbor at the creek mouth
BRIDGE_Y = -1255.0                       # green suspension bridge over the river mouth

DAY_LENGTH = 480.0
START_TOD = 0.32

PLAYER_MAX_HP = 100.0
START_MONEY = 350
HOSPITAL_FEE = 100
BUSTED_FEE = 150
WANTED_DECAY = 0.022
FOOT_SPEED = 5.2
FOOT_RUN = 9.0
CAM_DIST_FOOT = 7.0
CAM_DIST_CAR = 11.0
CAM_DIST_AIR = 17.0

MAX_PEDS = 34
MAX_TRAFFIC = 22
MAX_FREEWAY_CARS = 14
MAX_PARKED = 46
SPAWN_RING = (60.0, 190.0)
DESPAWN_R = 260.0

# traffic signals at major×major intersections; one global phase
LIGHT_PERIOD = 15.0        # v-green 6.5s, all-red 1s, h-green 6.5s, all-red 1s

TITLE = "ANGEL CITY"


def light_green(axis, t):
    """Which axis has green: shared phase citywide (v = avenues, h = streets)."""
    ph = (t % LIGHT_PERIOD) / LIGHT_PERIOD
    if axis == "v":
        return ph < 0.433
    return 0.5 <= ph < 0.933


def district_name(x, y):
    """Real LA neighborhood names at roughly correct relative positions."""
    if LAX_Y0 - 60 < y < LAX_Y1 + 40 and x < -1420:
        return "LAX"
    if y < PORT_Y0 + 220:
        return "San Pedro"
    if y > 860:
        if x < -700:
            return "Topanga"
        if x < 150:
            return "Hollywood Hills"
        if x < 700:
            return "Griffith Park"
        return "Elysian Park"
    if y > 640:
        if x < -450:
            return "West Hollywood"
        if x < 260:
            return "Hollywood"
        if x < 800:
            return "Los Feliz"
        return "Echo Park"
    if x < BEACHTOWN_X1:
        return "Santa Monica" if y > -150 else "Venice"
    dx0, dx1, dy0, dy1 = DOWNTOWN
    if dx0 <= x <= dx1 and dy0 <= y <= dy1:
        return "Downtown"
    px0, px1, py0, py1 = PARK
    if px0 <= x <= px1 and py0 <= y <= py1:
        return "Hancock Park"
    if y < INDUSTRIAL_Y1:
        if x > 820:
            return "Vernon"
        if x < -520:
            return "Inglewood"
        return "South Central"
    if -1050 <= x < -560 and y < 0:
        return "Culver City"
    if 0 <= x < 460 and -60 < y < 300:
        return "Koreatown"
    if x >= 960:
        return "Boyle Heights"
    return "Mid-City"
