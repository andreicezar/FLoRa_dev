# 📂 Documentație Simulări LoRaWAN – ADRopt

Această documentație acoperă scenariile de simulare organizate pe baza formulei folosite pentru PER, a valorii ADR Margin și a configurației de inițializare (SF/TP). Structura reflectă progresul implementării ADRopt și setările testate.

---

# 🧾 Rezumat configurații simulări

| Scenariu                                | Algoritm ADR | Noduri | Gateway-uri | Pachete/nod | Inițializare SF/TP        | Inițializare individuală? |
|-----------------------------------------|--------------|--------|-------------|-------------|----------------------------|----------------------------|
| DER_8GW10ED_ADRopt.ini                  | ADRopt       | 10     | 8           | 5000        | SF12, TP14                 | NU                         |
| DER_8GW10ED_ADRopt_different_init.ini   | ADRopt       | 10     | 8           | 5000        | VARIABILĂ pe fiecare nod   | DA                         |
| DER_8GW10ED_ADRavg.ini                  | ADRavg       | 10     | 8           | 5000        | SF12, TP14                 | NU                         |
| DER_8GW10ED_ADRavg_different_init.ini   | ADRavg       | 10     | 8           | 5000        | VARIABILĂ pe fiecare nod   | DA                         |
| DER_8GW1ED_ADRopt.ini                   | ADRopt       | 1      | 8           | 5000        | SF12, TP14                 | NU                         |
| DER_8GW1ED_ADRavg.ini                   | ADRavg       | 1      | 8           | 5000        | SF12, TP14                 | NU                         |

---

## 🔧 Parametri comuni

- **Durată simulare**: `sim-time-limit = 2.500.000s`
- **Canal propagare**: `LoRaLogNormalShadowing`
- **ADR activat**: atât la server, cât și la nod (`evaluateADRinServer = true`, `evaluateADRinNode = true`)
- **Model energie**: `LoRaEnergyConsumer`, parametri în `energyConsumptionParameters.xml`
- **ALOHA**: dezactivat (`alohaChannelModel = false`)
- **Timp între pachete**:
  - `timeToFirstPacket = exponential(10s)`
  - `timeToNextPacket = exponential(250s)`
- **Dimensiune topologie**: 5000m × 5000m
- **Dimensiune pachet transmis**: **20 bytes** (`LoRaApp.headerSize = 20B`)
- **Vector recording activ**: `**.radio.vector-recording = true`

---

## 🔍 Diferențe cheie între scenarii

| Scenariu                                | Formula PER                              | Selectare TP/SF finală             | Comentarii suplimentare                                      |
|-----------------------------------------|-------------------------------------------|------------------------------------|---------------------------------------------------------------|
| DER_8GW10ED_ADRopt.ini                  | ❌ Greșită: `∏(FER^nbTrans)`              | Nu setează `optimalTP/SF` final    | Versiune inițială cu logică ADRopt incompletă                |
| DER_8GW10ED_ADRopt_different_init.ini   | ❌ Greșită: `∏(FER^nbTrans)`              | Nu setează `optimalTP/SF` final    | Inițializare per nod unică, dar încă formulă PER greșită     |
| DER_8GW10ED_ADRavg.ini                  | N/A – medie SNIR                          | Ajustare clasică prin SNR margin   | Algoritm simplificat, fără predicții FER/PER                 |
| DER_8GW10ED_ADRavg_different_init.ini   | N/A – medie SNIR                          | Ajustare clasică prin SNR margin   | Inițializare individuală, dar fără optimizare ToA sau PER    |
| DER_8GW1ED_ADRopt.ini                   | ✅ Corectă: `(∏FER)^nbTrans`              | ✔️ Setează `optimalTP/SF` final    | Corect implementat ADRopt, dar test doar pe 1 nod            |
| DER_8GW1ED_ADRavg.ini                   | N/A – medie SNIR                          | Ajustare simplă prin SNR margin    | Control simplu ADR pe un singur nod                          |

---

## 🧠 Explicații:

- **Formulă PER**:
  - *Greșită*: exponentul `nbTrans` aplicat fiecărui FER
  - *Corectă*: exponent aplicat după produsul FER-urilor

- **Setare finală TP/SF**:
  - Inițial: întotdeauna `TP=14`, `SF=din frame`
  - Corect: `optimalTP` și `optimalSF` sunt inserate în frame-ul ADR de răspuns

- **ADRavg**:
  - Nu folosește istoric SNIR pentru predicție PER
  - Bazează decizia doar pe medie SNIR și marja SNR

- **Scenariile `*_different_init.ini`**:
  - Nodurile au TP și SF inițiale diferite pentru testare convergență

---

## 🧪 Scenario 0

### 📝 Descriere
- **Formula greșită** pentru calculul `PER(sf, nbTrans)`:
PER = ∏ (FER^NbTrans)
(exponențierea aplicată **pe fiecare gateway separat**)

### 🔧 Configurații
- `adr_margin_0`:  
- ADR Margin = **0**
- Inițializare: `SF=12`, `TP=14`  
- Export JSON: `export_json_adr_margin_0`
- Rezultate: `results_adr_margin_0`

- `adr_margin_15`:  
- ADR Margin = **15**
- Inițializare: `SF=12`, `TP=14`  
- Export JSON: `export_json_adr_margin_15`
- Rezultate: `results_adr_margin_15`

- `adr_margin_15_different_init`:  
- ADR Margin = **15**
- Inițializare diferită (alt `SF`, `TP`)  
- Export JSON: `export_json_adr_margin_15_different_init`
- Rezultate: (în cadrul `results_adr_margin_15`)

---

## 🧪 Scenario 1

### 📝 Descriere
- **Formula corectată** pentru `PER(sf, nbTrans)`:
PER = (∏ FER)^NbTrans
(exponențierea aplicată **după produsul FER-urilor**)

### 🔧 Configurații
- `adr_margin_15_corrected`:  
- ADR Margin = **15**
- Inițializare: `SF=12`, `TP=14`  
- Export JSON: `export_json_adr_margin_15_corrected`
- Rezultate: `results_adr_margin_15_corrected`

- `adr_margin_15_corrected_different_init`:  
- ADR Margin = **15**
- Inițializare diferită  
- Export JSON: inclus în `export_json_adr_margin_15_corrected`
- Rezultate: incluse în `results_adr_margin_15_corrected`

---

## 🧪 Scenario 2

### 📝 Descriere
- Formula `PER(sf, nbTrans)` este **corectată** ca în Scenario 1.
- În plus:
- La **finalul transmisiei**, se setează:
  ```cpp
  frame->setLoRaSF(optimalSF);
  frame->setLoRaTP(optimalTP);
  ```
  și **nu** valorile fixe `SF din frame` și `TP = 14`.

### 🔧 Configurații
- `adr_margin_15_set_fin_opt_sf_tp`:  
- ADR Margin = **15**
- Inițializare: `SF=12`, `TP=14`  
- Export JSON: `export_json_adr_margin_15_set_fin_opt_sf_tp`
- Rezultate: `results_adr_margin_15_set_fin_opt_sf_tp`

- `adr_margin_15_set_fin_opt_sf_tp_different_init`:  
- ADR Margin = **15**
- Inițializare diferită  
- Export JSON: inclus în `export_json_adr_margin_15_set_fin_opt_sf_tp`
- Rezultate: incluse în `results_adr_margin_15_set_fin_opt_sf_tp`

---

## Structură directoare relevante

simulation_tool
├── config_files_for_scenarios
├── examples
├── results_and_analysis
├── scenario_0
│   ├── export_json_adr_margin_0
│   ├── export_json_adr_margin_15
│   ├── export_json_adr_margin_15_different_init
│   ├── results_adr_margin_0
│   └── results_adr_margin_15
├── scenario_1
│   ├── export_json_adr_margin_15_corrected
│   └── results_adr_margin_15_corrected
├── scenario_2
│   ├── export_json_adr_margin_15_set_fin_opt_sf_tp
│   └── results_adr_margin_15_set_fin_opt_sf_tp
└── scripts
    ├── plots_adr_margin_0
    ├── plots_adr_margin_15
    ├── plots_adr_margin_15_corrected
    └── plots_metrics_extractor


## 📌 Observații
- Fiecare subfolder conține:
  - `*.json` → exporturi din `sca`, `vec`, `histograms`, `parameters`
  - `*.ini`, `*.vec`, `*.sca` → rezultate brute
- Simulările sunt organizate cronologic și reflectă corectitudinea progresivă a algoritmului ADRopt implementat în `evaluateADR()`.
