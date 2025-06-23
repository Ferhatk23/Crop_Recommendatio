# Streamlit ist eine Bibliothek, mit der man einfach Web-Apps in Python erstellen kann
import streamlit as st

# Pandas wird verwendet, um tabellarische Daten (wie in Excel) zu verarbeiten
import pandas as pd

# joblib dient zum Laden bereits gespeicherter Modelle (z. B. das trainierte Vorhersagemodell)
import joblib

# Hier wird ein Wörterbuch (dictionary) erstellt:
# Für jede Pflanze wird ein passendes Bild aus dem Internet zugewiesen.
# Wenn später eine Pflanze empfohlen wird, kann direkt das passende Bild angezeigt werden.
CROP_IMAGES = {
    "rice": "https://upload.wikimedia.org/wikipedia/commons/6/6d/Jasmin_Reis.jpg",
    "maize": "https://upload.wikimedia.org/wikipedia/commons/2/28/Zea_mays.jpg",
    "chickpea": "https://upload.wikimedia.org/wikipedia/commons/8/8a/Chickpeas.JPG",
    "kidneybeans": "https://upload.wikimedia.org/wikipedia/commons/8/8b/Kidney_beans.jpg",
    "pigeonpeas": "https://upload.wikimedia.org/wikipedia/commons/2/2f/Pigeon_peas.jpg",
    "mothbeans": "https://upload.wikimedia.org/wikipedia/commons/2/2f/Matki.JPG",
    "mungbean": "https://upload.wikimedia.org/wikipedia/commons/c/c3/06991jfCuisine_Foods_Landmarks_Baliuag_Bulacanfvf_04.jpg",
    "blackgram": "https://upload.wikimedia.org/wikipedia/commons/6/6f/Black_gram.jpg",
    "lentil": "https://upload.wikimedia.org/wikipedia/commons/d/da/3_types_of_lentil.jpg",
    "pomegranate": "https://upload.wikimedia.org/wikipedia/commons/d/da/Granat%C3%A4pfel.JPG",
    "banana": "https://upload.wikimedia.org/wikipedia/commons/8/8a/Banana-Single.jpg",
    "mango": "https://upload.wikimedia.org/wikipedia/commons/9/90/Hapus_Mango.jpg",
    "grapes": "https://upload.wikimedia.org/wikipedia/commons/6/6e/003_Trauben_an_einer_Rebe_in_Fushe_Kupe.JPG",
    "watermelon": "https://upload.wikimedia.org/wikipedia/commons/2/2e/Wassermelone.jpg",
    "muskmelon": "https://upload.wikimedia.org/wikipedia/commons/f/ff/Muskmelon.jpg",
    "apple": "https://upload.wikimedia.org/wikipedia/commons/1/15/Red_Apple.jpg",
    "orange": "https://upload.wikimedia.org/wikipedia/commons/c/c4/Orange-Fruit-Pieces.jpg",
    "papaya": "https://upload.wikimedia.org/wikipedia/commons/0/09/Papaya_-_longitudinal_section.jpg",
    "coconut": "https://upload.wikimedia.org/wikipedia/commons/5/51/Brokencoconut.jpg",
    "cotton": "https://upload.wikimedia.org/wikipedia/commons/2/24/Cotton_Plant.png",
    "jute": "https://upload.wikimedia.org/wikipedia/commons/f/fa/Asahimo.jpg",
    "coffee": "https://upload.wikimedia.org/wikipedia/commons/4/44/16_105_Coffee_Beans_%28143302089%29.jpeg"
}

# Der Titel der Seite – wird ganz oben groß angezeigt
st.title("Crop Recommendation System")

# Untertitel – eine kurze Erklärung unter dem Titel
st.subheader("Geben Sie Ihre Umweltdaten ein, um eine Pflanze empfohlen zu bekommen")

# Zwei gleich breite Spalten: links die Eingabemaske, rechts das Ergebnis mit Bild
col1, col2 = st.columns([1, 1])  # [1, 1] bedeutet: beide Spalten sind gleich breit

# Inhalt der linken Spalte – hier gibt der Benutzer seine Werte ein
with col1:
    # Jede Zeile ist ein Eingabefeld mit Startwert und erlaubtem Bereich
 # Eingabefelder für alle relevanten Umweltdaten
    # Der Nutzer gibt Werte ein, z. B. wie viel Stickstoff im Boden ist
    N = st.number_input("Nitratgehalt im Boden (N)", value=50, min_value=0, max_value=140, step=1, help="Wert zwischen 0 und 140 kg/ha eingeben")
    P = st.number_input("Phosphorgehalt im Boden (P)", value=50, min_value=5, max_value=145, step=1, help="Wert zwischen 5 und 145 kg/ha eingeben")
    K = st.number_input("Kaliumgehalt im Boden (K)", value=50, min_value=5, max_value=205, step=1, help="Wert zwischen 5 und 205 kg/ha eingeben")
    temperature = st.number_input("Temperatur (°C)", value=25.0, min_value=0.0, max_value=43.0, step=0.1, help="Wert zwischen 0 und 43 Grad Celsius eingeben")
    humidity = st.number_input("Luftfeuchtigkeit (%)", value=60.0, min_value=14.0, max_value=100.0, step=0.1, help="Wert zwischen 14 und 100 Prozent eingeben")
    ph = st.number_input("pH-Wert", value=6.5, min_value=3.5, max_value=9.5, step=0.1, help="Wert zwischen 3.5 und 9.5 eingeben")
    rainfall = st.number_input("Niederschlag (mm)", value=100.0, min_value=20.0, max_value=300.0, step=0.1, help="Wert zwischen 20 und 300 mm eingeben")

    
    # Wenn der Benutzer auf den Button klickt, wird die Vorhersage gestartet
    submit = st.button("Empfehlung anzeigen")

# Inhalt der rechten Spalte – hier wird das Ergebnis dargestellt
with col2:
    if submit:
        # Das gespeicherte Modell und der Skalierer werden geladen
        model = joblib.load('crop_recommendation_rf_model.pkl')
        scaler = joblib.load('crop_recommendation_scaler.pkl')
        
        # Die Eingaben des Benutzers werden in eine Tabelle (DataFrame) umgewandelt
        input_df = pd.DataFrame({
            'N': [N], 'P': [P], 'K': [K],
            'temperature': [temperature],
            'humidity': [humidity],
            'ph': [ph],
            'rainfall': [rainfall]
        })

        # Die Eingaben werden standardisiert – das ist notwendig, weil das Modell so trainiert wurde
        input_scaled = scaler.transform(input_df)

        # Das Modell gibt eine Vorhersage aus – welche Pflanze ist geeignet?
        prediction = model.predict(input_scaled)[0]

        # Die Pflanze wird als Text angezeigt
        st.markdown(f"**Empfohlene Pflanze:** {prediction.capitalize()}")

        # Wenn es ein Bild zur Pflanze gibt, wird es angezeigt
        if prediction in CROP_IMAGES:
            st.image(CROP_IMAGES[prediction], caption=prediction.capitalize())
        else:
            # Falls kein Bild gefunden wurde, erscheint eine kurze Info
            st.info("Kein Bild für diese Pflanze verfügbar.")
