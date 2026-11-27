import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Eigedomsoppslag", page_icon="📍", layout="wide")

STANDARD_LAT = 60.385399
STANDARD_LON = 5.332843

if "lat" not in st.session_state:
    st.session_state.lat = STANDARD_LAT
if "lon" not in st.session_state:
    st.session_state.lon = STANDARD_LON

# Sørg for at input-feltene følger lat/lon før widgetene tegnes
if "lat_input" not in st.session_state:
    st.session_state.lat_input = st.session_state.lat
if "lon_input" not in st.session_state:
    st.session_state.lon_input = st.session_state.lon

st.title("📍 Finn eigedommen")
st.write(
    "Samarbeidsdeskens eigedomsjaktverktøy! Klikk direkte i kartet **eller** skriv inn breiddegrad og lengdegrad manuelt."
)

# 1. Initialiser koordinatar i session_state (Bergen sentrum som standard)
if "lat" not in st.session_state:
    st.session_state.lat = 60.385262
if "lon" not in st.session_state:
    st.session_state.lon = 5.322961
if "lat_input" not in st.session_state:
    st.session_state.lat_input = st.session_state.lat
if "lon_input" not in st.session_state:
    st.session_state.lon_input = st.session_state.lon
if "sist_klikket" not in st.session_state:
    st.session_state.sist_klikket = None


def oppdater_fra_input():
    st.session_state.lat = st.session_state.lat_input
    st.session_state.lon = st.session_state.lon_input


@st.cache_data(ttl=3600, show_spinner=False)
def hent_kommunenavn(latitude: float, longitude: float) -> str:
    """Hentar kommunenamn for punktet frå Geonorge sitt kommune-API."""
    try:
        resp = requests.get(
            "https://ws.geonorge.no/kommuneinfo/v1/punkt",
            params={"nord": latitude, "ost": longitude, "koordsys": 4326},
            timeout=5,
        )
        if resp.ok:
            return resp.json().get("kommunenavn", "")
    except requests.RequestException:
        pass
    return ""


@st.cache_data(ttl=600, show_spinner=False)
def finn_eiendom(latitude: float, longitude: float) -> tuple[list[dict], dict]:
    """Slår opp eigedom på punktet via Geonorge sitt opne REST-API (GeoJSON)."""
    url = "https://ws.geonorge.no/eiendom/v1/punkt/omrader"
    params = {
        "nord": latitude,
        "ost": longitude,
        "koordsys": 4326,
        "radius": 1,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    geojson_data = resp.json()

    knavn = hent_kommunenavn(latitude, longitude)

    features = geojson_data.get("features", [])
    elementer = (
        [f.get("properties", {}) for f in features]
        if features
        else geojson_data.get("eiendom", [])
    )

    funn = []
    sett = set()

    for props in elementer:
        knr = str(props.get("kommunenummer", "")).zfill(4)
        gnr = int(props.get("gardsnummer") or 0)
        bnr = int(props.get("bruksnummer") or 0)
        fnr = int(props.get("festenummer") or 0)
        snr = int(props.get("seksjonsnummer") or 0)

        if not knr or knr == "0000":
            continue

        nokkel = (knr, gnr, bnr, fnr, snr)
        if nokkel not in sett:
            sett.add(nokkel)
            funn.append(
                {
                    "kommunenummer": knr,
                    "kommunenavn": knavn,
                    "gardsnummer": gnr,
                    "bruksnummer": bnr,
                    "festenummer": fnr,
                    "seksjonsnummer": snr,
                    "matrikkelnummertekst": props.get("matrikkelnummertekst", ""),
                    "teigmedflerematrikkelenheter": bool(
                        props.get("teigmedflerematrikkelenheter", False)
                    ),
                }
            )

    reelle = [u for u in funn if not (u["gardsnummer"] == 0 and u["bruksnummer"] == 0)]
    return (reelle if reelle else funn), geojson_data


@st.cache_data(ttl=600, show_spinner=False)
def hent_veiadresse_hvis_finnes(
    latitude: float, longitude: float, knr: str, gnr: int, bnr: int
) -> str | None:
    """Hentar vegadresse på same gnr/bnr viss ho eksisterer."""
    url = "https://ws.geonorge.no/adresser/v1/punktsok"
    params = {"lat": latitude, "lon": longitude, "radius": 200, "treffPerSide": 10}
    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        for adr in resp.json().get("adresser", []):
            if (
                str(adr.get("kommunenummer")).zfill(4) == knr
                and adr.get("gardsnummer") == gnr
                and adr.get("bruksnummer") == bnr
            ):
                tekst = adr.get("adressetekst") or adr.get(
                    "adressetekstutenadressetilleggsnavn"
                )
                if tekst:
                    return tekst
    except requests.RequestException:
        pass
    return None


lat_aktiv = st.session_state.lat
lon_aktiv = st.session_state.lon

feilmelding = None
eiendommer = []
raa_geojson = {}

try:
    eiendommer, raa_geojson = finn_eiendom(lat_aktiv, lon_aktiv)
except requests.RequestException as e:
    feilmelding = f"Kunne ikkje kontakte Kartverkets teneste: {e}"

# To hovudkolonnar: Input og resultat til venstre (2), kart til høgre (3)
info_kol, kart_kol = st.columns([2, 3], gap="large")

# NB: Vi køyrer framleis kart_kol først i koden slik at kartklikk oppdaterer
# session_state FØR number_input blir teikna i info_kol til venstre.
with kart_kol:
    m = folium.Map(
        location=[lat_aktiv, lon_aktiv],
        zoom_start=17,
        tiles=(
            "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
        ),
        attr='&copy; <a href="https://www.kartverket.no/">Kartverket</a>',
    )

    if raa_geojson.get("features"):
        folium.GeoJson(
            raa_geojson,
            name="Eigedomsteig",
            style_function=lambda _: {
                "color": "#0055ff",
                "weight": 3,
                "fillColor": "#0055ff",
                "fillOpacity": 0.18,
            },
        ).add_to(m)

    folium.Marker(
        location=[lat_aktiv, lon_aktiv],
        tooltip=f"{lat_aktiv:.6f}, {lon_aktiv:.6f}",
        icon=folium.Icon(color="red", icon="info-sign"),
    ).add_to(m)

    kart_data = st_folium(
        m,
        height=540,
        use_container_width=True,
        returned_objects=["last_clicked"],
    )

    if kart_data and kart_data.get("last_clicked"):
        klikk = (
            round(kart_data["last_clicked"]["lat"], 6),
            round(kart_data["last_clicked"]["lng"], 6),
        )
        if klikk != st.session_state.sist_klikket:
            st.session_state.sist_klikket = klikk
            st.session_state.lat = klikk[0]
            st.session_state.lon = klikk[1]
            st.session_state.lat_input = klikk[0]
            st.session_state.lon_input = klikk[1]
            st.rerun()

with info_kol:
    st.subheader("Koordinatar (WGS84)")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input(
            "Latitude (breiddegrad)",
            format="%.6f",
            step=0.0001,
            key="lat_input",
            on_change=oppdater_fra_input,
        )
    with c2:
        st.number_input(
            "Longitude (lengdegrad)",
            format="%.6f",
            step=0.0001,
            key="lon_input",
            on_change=oppdater_fra_input,
        )

    st.divider()
    st.subheader("Vald eigedom")

    if feilmelding:
        st.error(feilmelding)
    elif not eiendommer:
        st.warning(
            "Fann ingen registrert eigedom på dette punktet (t.d. ope hav eller utanfor Noreg)."
        )
    else:
        hoved = eiendommer[0]
        knr = hoved["kommunenummer"]
        knavn = hoved["kommunenavn"]
        gnr = hoved["gardsnummer"]
        bnr = hoved["bruksnummer"]
        fnr = hoved["festenummer"]
        snr = hoved["seksjonsnummer"]

        if gnr == 0 and bnr == 0:
            st.info(
                f"Punktet ligg i **{knavn or knr}**, men på umatrikulert grunn / sjøareal (Gnr 0 / Bnr 0)."
            )
        else:
            adresse = hent_veiadresse_hvis_finnes(lat_aktiv, lon_aktiv, knr, gnr, bnr)
            eiendom_url = (
                f"https://eiendomsregisteret.kartverket.no/eiendom/{knr}/{gnr}/{bnr}/{fnr}/{snr}"
            )

            m1, m2 = st.columns(2)
            m1.metric("Kommune", f"{knavn} ({knr})" if knavn else knr)
            m2.metric("Gnr / Bnr", f"{gnr} / {bnr}")

            if fnr > 0 or snr > 0:
                st.caption(f"Festenummer: **{fnr}** · Seksjonsnummer: **{snr}**")

            if hoved.get("teigmedflerematrikkelenheter"):
                st.caption(
                    "ℹ️ Teigen er registrert med fleire matrikkeleiningar (t.d. sameige eller seksjonert eigedom)."
                )

            if adresse:
                st.write(f"**Vegadresse:** {adresse}")
            else:
                st.info("Ingen registrert vegadresse på denne eigedomen.")

            st.link_button(
                "Opne Kartverkets eigedomsregister ↗",
                eiendom_url,
                type="primary",
                use_container_width=True,
            )

            if len(eiendommer) > 1:
                with st.expander(
                    f"Sjå alle {len(eiendommer)} matrikkeleiningane på teigen"
                ):
                    for e in eiendommer:
                        e_url = (
                            f"https://eiendomsregisteret.kartverket.no/eiendom/"
                            f"{e['kommunenummer']}/{e['gardsnummer']}/{e['bruksnummer']}/"
                            f"{e['festenummer']}/{e['seksjonsnummer']}"
                        )
                        st.markdown(
                            f"- **Gnr {e['gardsnummer']} / Bnr {e['bruksnummer']}** "
                            f"(Fnr {e['festenummer']}, Snr {e['seksjonsnummer']}) – "
                            f"[Opne]({e_url})"
                        )