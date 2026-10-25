# STRATEGY PLAYBOOK: SISTEM TRADING MOMENTUM BERBASIS VOLUME PROFILE & SMART RISK MANAGEMENT
**Dokumentasi Referensi Teknis & Standar Operasional Prosedur (SOP)**  
**Target Aplikasi:** Portofolio Saham Ekuitas Likuid (S&P 100 / Large-Cap US Equities)  
**Tujuan Utama:** Menghasilkan Alfa di atas Benchmark (SPY) melalui Penangkapan Tren Institusional, Mengeliminasi *Whipsaw Shakeout*, dan Mengoptimalkan Efisiensi Rebalancing (*Compounding*).

---

## DAFTAR ISI
1. [Filosofi Inti & Landasan Kuantitatif](#1-filosofi-inti--landasan-kuantitatif)
2. [Pilar 1: Konsep & Mekanika Volume Profile (VPVR)](#2-pilar-1-konsep--mekanika-volume-profile-vpvr)
3. [Pilar 2: Taksonomi 3 Setup Utama (Entry Architecture)](#3-pilar-2-taksonomi-3-setup-utama-entry-architecture)
4. [Pilar 3: Exit Rules & Quantitative Risk Management](#4-pilar-3-exit-rules--quantitative-risk-management)
5. [Pilar 4: Smart Band Rebalancing & Holding Hysteresis Buffer](#5-pilar-4-smart-band-rebalancing--holding-hysteresis-buffer)
6. [SOP Checklist Keputusan Periodik](#6-sop-checklist-keputusan-periodik)

---

## 1. Filosofi Inti & Landasan Kuantitatif

Berdasarkan hasil evaluasi *forward-test* historis (2025–2026), performa strategi tertekan bukan karena kelemahan *stock-picking*, melainkan karena **eksekusi mikro yang terlalu sensitif, stop loss statis yang mengabaikan volatilitas aset, dan *whipsaw* likuidasi pada titik balik tren**.

Playbook ini dirancang di atas empat hukum kuantitatif:
1. **Asymmetric Payoff (*Cut Losers Early, Let Winners Run*):** Keuntungan terbesar portofolio dihasilkan oleh 10–20% posisi pemenang super (*secular compounders* seperti MU, AMD, NVDA). Sistem dilarang memotong pemenang secara prematur hanya karena rebalance desimal.
2. **Institutional Footprints Over Price Alone:** Harga dapat dimanipulasi dalam jangka pendek, namun volume transaksi per tingkat harga (*Volume Profile*) mencerminkan jejak komitmen modal institusi besar.
3. **Volatility-Aware Execution:** Parameter risiko harus dinamis mengikuti *Average True Range* (ATR). Menerapkan persentase stop loss seragam pada aset bervolatilitas berbeda adalah kegagalan desain matematis.
4. **Execution Friction Control:** Mengurangi *turnover* berlebihan dan mematikan mikro-transaksi yang menguras biaya komisi dan memicu *slippage*.

---

## 2. Pilar 1: Konsep & Mekanika Volume Profile (VPVR)

Volume Profile Visible Range (VPVR) memetakan total volume transaksi pada sumbu harga vertikal, bukan pada sumbu waktu horizontal. Ini mengungkap level konsensus harga (*Fair Value*) dan zona ketidakseimbangan likuiditas (*Imbalance*).

```
   Harga ($)           Volume Transaksi (VPVR)         Klasifikasi Struktur
     120    |                                          [ Resistance LVN ]
     115    |=======================                   [ HVN / Target 2 ]
     110    |===                                       [ LVN - Fast Travel Zone ]
     105    |========================================  [ POC - Point of Control ]
     100    |=================================         [ HVN / Strong Support Shelf ]
      95    |==                                        [ LVN - Rejection Zone ]
```

### 2.1. Definisi & Karakteristik Komponen Utama

#### A. Point of Control (POC)
- **Definisi:** Level harga tunggal dengan volume transaksi paling masif di dalam rentang waktu yang dianalisis.
- **Karakteristik:** 
  - Mencerminkan *Fair Value* absolut atau konsensus harga paling disepakati antara pembeli dan penjual institusional.
  - Berfungsi sebagai **magnet harga** saat pasar berkonsolidasi (*mean reversion target*), dan menjadi bantalan support/resistance terkuat ketika diuji dari arah berlawanan.

#### B. High Volume Nodes (HVN)
- **Definisi:** Gugusan harga horizontal yang membentuk tonjolan volume tinggi (*volume peaks* atau *shelves*).
- **Karakteristik:**
  - Menandai zona di mana institusi telah melakukan akumulasi atau distribusi dalam durasi yang panjang.
  - **Sifat Mekanis:** Ketika harga bergerak turun mendekati HVN dari atas, HVN bertindak sebagai **support struktural tangguh**. Likuiditas yang tebal membutuhkan tekanan jual luar biasa besar untuk ditembus.
  - Pergerakan harga di area HVN cenderung melambat dan berkonsolidasi karena terjadi rotasi likuiditas tinggi.

#### C. Low Volume Nodes (LVN)
- **Definisi:** Cekungan lembah pada profil volume (*volume valleys*) di mana sangat sedikit transaksi yang terjadi.
- **Karakteristik:**
  - Menandai zona penolakan harga (*price rejection* / *unfair value*). Pelaku pasar menganggap harga bergerak terlalu cepat di zona ini.
  - **Sifat Mekanis:** LVN bertindak sebagai **Fast Travel Zone / Slippage Pocket**. Jika harga menembus batas HVN dan masuk ke LVN, harga akan bergerak sangat cepat dan volatil menuju HVN berikutnya tanpa resistensi berarti.
  - LVN atas bertindak sebagai resistensi dinamis di mana momentum sering kehabisan bahan bakar jika tidak didukung volume baru.

---

### 2.2. Aturan Taktis Trading VPVR

1. **Beli di Support HVN / POC (Value Shelf Buying):**
   - Entry dilakukan saat harga terkoreksi kembali (*pullback*) ke arah rak volume HVN atau level POC yang bertepatan dengan moving average utama (SMA20/SMA50).
   - Hindari membeli tepat di udara hampa (di tengah LVN lebar) karena tidak ada bantalan likuiditas jika terjadi penurunan lanjutan.
2. **Jual / Take Profit di Resistance LVN / HVN Berikutnya:**
   - Jadwalkan target take profit atau *trailing exit* tepat sebelum harga memasuki LVN atas atau tepat pada dinding batas bawah HVN berikutnya di atas.
3. **Prinsip Breakout LVN:**
   - Jika harga berhasil menembus resistensi HVN dengan volume ledakan, tahan posisi dengan keyakinan tinggi karena harga akan melintasi kantong LVN dengan kecepatan akselerasi tinggi (*fast-travel*).

---

## 3. Pilar 2: Taksonomi 3 Setup Utama (Entry Architecture)

Setiap entri portofolio WAJIB memenuhi salah satu dari tiga taksonomi setup mekanis berikut. Posisi tanpa konfirmasi setup dilarang dibuka.

```
                      +-----------------------------+
                      |   STRUKTUR PASAR & TREND    |
                      +-----------------------------+
                                     |
         +---------------------------+---------------------------+
         |                                                       |
[ UPTREND KUAT ]                                        [ BASE / SUPPORT MAYOR ]
(Close > SMA50 > SMA200)                                (Rebound di HVN / 60d Low)
         |                                                       |
   +-----+-----+                                                 |
   |           |                                                 |
[Breakout]  [Pullback]                                      [Reversal]
   |           |                                                 |
   v           v                                                 v
SETUP 1     SETUP 2                                           SETUP 3
CONTINUATION PULLBACK                                          REVERSAL
```

---

### SETUP 1: CONTINUATION (Momentum Breakout)
*Menangkap akselerasi harga saat saham menembus resistensi konsolidasi menuju rekor harga baru.*

- **Logika Pasar:** Pembeli institusional menyerap seluruh pasokan di resistensi lokal dan mendorong harga ke fase *price discovery*.
  1. **Kondisi Tren:** Saham berada dalam status **UPTREND** penuh ($\text{Close} > \text{SMA}_{50} > \text{SMA}_{200}$).
  2. **Struktur Harga:** Harga penutupan menembus atau berada di ambang tertinggi 20-bar ($\text{Close} \ge 0.97 \times \text{High}_{20}$).
  3. **Konfirmasi Volume:** Volume transaksi harian melonjak ekspansif:
     $$\text{Volume} \ge 1.25 \times \text{SMA Volume}_{20}$$
  4. **Profil Volume (VPVR):** Harga berhasil melintasi batas atas HVN lokal dan siap berakselerasi melintasi zona LVN di atasnya.
  5. **Filter Lilin Akumulasi Wajib (*Bullish Accumulation Candle*):**
     $$\text{Close} \ge \text{Open} \quad (\text{last\_c} \ge \text{last\_o})$$
     *Rasional Kuantitatif:* Filter lilin hijau/akumulasi ini wajib dipenuhi untuk mengeliminasi *distribution bar fakeouts* dan jebakan *bull trap* di dekat rekor tertinggi 20-bar di mana institusi melepas posisi ke pembeli retail. Lilin harus berupa *bullish expansion bar* tanpa *upper rejection wick* tebal.
  6. **Penempatan Stop Awal:** Tepat di bawah *low* lilin breakout atau batas bawah HVN terdekat.
- **Target Alokasi Modal:** Bobot penuh (misal 8–10% per ticker).

---

### SETUP 2: PULLBACK (Low-Risk Trend Retest)
*Membeli koreksi sehat pada saham berfundamental kuat di dalam tren naik utama.*

- **Logika Pasar:** Aksi ambil untung jangka pendek dari *retail traders* yang ditampung secara tenang oleh institusi di area nilai wajar.
- **Kriteria Kuantitatif Wajib:**
  1. **Kondisi Tren:** Saham berada dalam **UPTREND** mapan ($\text{Close} > \text{SMA}_{50}$ dan $\text{SMA}_{50}$ mengarah ke atas).
  2. **Lokasi Retest:** Harga menguji zona pertemuan teknikal (*confluence zone*):
     - Berada dalam jarak $\pm 2\%$ dari $\text{SMA}_{20}$ ATAU $\pm 3\%$ dari $\text{SMA}_{50}$.
     - **DAN** bertepatan dengan rak support HVN atau POC 60-hari.
  3. **Pengeringan Volume (*Volume Drying Up*):** Selama 2–3 bar koreksi, volume harus mengering:
     $$\text{Volume saat retest} < 1.15 \times \text{SMA Volume}_{20} \quad (\text{ideal } < 0.85\times)$$
     *Artinya: Tidak ada tekanan jual distribusi institusional.*
  4. **Osilator Momentum:** $\text{RSI}_{14}$ berada di rentang koreksi wajar: $35 \le \text{RSI}_{14} \le 52$.
  5. **Pemicu Lilin Rebound:** Muncul *bullish reversal bar* (misal: Bullish Engulfing, Hammer, atau Inside Bar breakout) yang ditutup menguat ($\text{Close} > \text{Open}$ dan $\text{Close} > \text{High}_{-1}$).
- **Target Alokasi Modal:** Bobot penuh (misal 8–10% per ticker).
- **Penempatan Stop Awal:** $\max(\text{Low swing pullback}, \text{Level HVN bawah})$.

---

### SETUP 3: REVERSAL (Liquidity Sweep & Value Absorption)
*Menangkap pembalikan arah tajam di batas bawah struktur pasar setelah pasokan habis terserap.*

- **Logika Pasar:** Institusi menyerap *stop loss panic selling* (*liquidity hunt*) di level diskon ekstrem dan membalikkan arah kendali pasar.
- **Kriteria Kuantitatif Wajib:**
  1. **Level Kritis:** Harga menyentuh level support mayor 60-bar low atau batas bawah kluster HVN/POC utama dalam toleransi $\pm 2\%$.
  2. **Volume Climax / Absorption:** Volume transaksi meledak sangat tinggi:
     $$\text{Volume} \ge 1.40 \times \text{SMA Volume}_{20}$$
  3. **Karakteristik Candlestick Rejection:**
     - Lilin berjenis *Hammer* / *Bullish Pin Bar* dengan sumbu bawah panjang (*lower rejection wick*) yang mendominasi:
       $$\text{Lower Wick} \ge 50\% \text{ dari total } (\text{High} - \text{Low})$$
     - Harga penutupan harian harus berada di separuh atas rentang lilin ($\text{Close} \ge \text{Low} + 0.50 \times (\text{High} - \text{Low})$).
  4. **Status Tren:** Dapat terjadi di saham DOWNTREND yang sedang *oversold* parah ($\text{RSI} < 35$) atau UPTREND yang mengalami koreksi dalam.
- **Target Alokasi Modal:** Bobot taktis separuh (misal 4–5% per ticker) karena melawan momentum jangka pendek; tambahkan bobot setelah tren terkonfirmasi naik kembali.
- **Siklus Hidup Stop Dinamis (3-Stage Dynamic Stop Lifecycle):**
  Entri *reversal* institusional memiliki karakteristik risiko asimetris: probabilitas *bottoming* tinggi namun rentan terhadap *liquidity re-test*. Sistem menerapkan siklus proteksi modal 3 tahap:
  1. **Stage 1 (Initial Tight Stop 4.5% – 5.0%):**
     Saat posisi baru dibuka, risiko dibatasi sangat ketat ($\text{Stop Loss} = \text{Entry} \times (1 - 0.050)$ atau tepat di bawah sumbu *wick low* lilin absorption). Ini memastikan kerugian langsung diputus jika level support institusional jebol.
  2. **Stage 2 (Breakeven Lock at +8%):**
     Begitu keuntungan yang belum direalisasi mencapai gain $\ge +8.0\%$ dari harga entri ($\text{High-Water Mark} \ge \text{Entry} \times 1.08$), level stop loss **otomatis dinaikkan ke harga beli (Breakeven: $\text{Stop} = \text{Entry}$)**. Posisi kini berstatus *risk-free trade*.
  3. **Stage 3 (Runner Trailing Stop 12% at +20%):**
     Ketika posisi berkembang menjadi pemenang kuat dengan gain $\ge +20.0\%$ ($\text{High-Water Mark} \ge \text{Entry} \times 1.20$), posisi diklasifikasikan sebagai *Super Runner*. Proteksi dialihkan ke mekanisme *trailing stop* 12% dari High-Water Mark:
     $$\text{Stop Price} = \text{High-Water Mark} \times (1 - 0.12)$$
     Hal ini memberi ruang napas bagi tren sekuler untuk *let winners run* hingga puluhan/ratusan persen tanpa terlempar oleh rebalancing kalender.

---

## 4. Pilar 3: Exit Rules & Quantitative Risk Management

Kelemahan terbesar sistem masa lalu adalah stop loss 8% tetap yang dieksekusi pada *intraday low*, memicu 58.9% likuidasi palsu. Pilar ini merestrukturisasi manajemen risiko secara komprehensif.

```
       +-------------------------------------------------------+
       |             MANAJEMEN RISIKO POSISI AKTIF             |
       +-------------------------------------------------------+
                                   |
         +-------------------------+-------------------------+
         |                         |                         |
[ TRAILING STOP ATR ]    [ STRUCTURAL BREAKDOWN ]    [ PROFIT OVERBOUGHT ]
EOD Close vs Stop        Close < SMA50 / Swing Low   RSI > 80 di Resistance
Protect Volatility       Trend Invalidation          Scale-out Take Profit
```

### 4.1. Volatility-Adjusted Trailing Stop (Berdasarkan ATR & High-Water Mark)

- **Eliminasi Stop Statis 8%:** Saham bervolatilitas tinggi seperti MU (ATR 5.7%) atau AMD (ATR 5.0%) tidak boleh disamakan dengan saham utilitas/defensif bervolatilitas rendah (JNJ, KO).
- **Formula Jarak Stop Dinamis:**
  $$\text{Stop Distance \%} = \max\Big(8.0\%,\; 2.5 \times \text{ATR}_{14}\%\Big)$$
  *Contoh Perhitungan:*
  - Saham A (Defensif): $\text{ATR}_{14}\% = 2.0\% \rightarrow \text{Stop Distance} = \max(8.0\%, 5.0\%) = \mathbf{8.0\%}$.
  - Saham B (Semikonduktor): $\text{ATR}_{14}\% = 5.5\% \rightarrow \text{Stop Distance} = \max(8.0\%, 13.75\%) = \mathbf{13.75\%}$.
- **Mekanika High-Water Mark Trailing Stop:**
  Untuk setiap hari bursa $t$:
  $$\text{High-Water Mark } (HWM_t) = \max_{i \le t}(\text{Close}_i)$$
  $$\text{Stop Price}_t = HWM_t \times \big(1 - \text{Stop Distance \%}\big)$$
  *Level Stop Price hanya boleh naik, tidak pernah boleh diturunkan.*

---

### 4.2. Aturan Konfirmasi Penutupan (End-of-Day Close Trigger)
*Solusi terhadap 58.9% Intraday Wick Shakeout*

- **Aturan Eksekusi:** Stop loss **TIDAK BOLEH** dipicu secara instan oleh *intraday low wick* sesaat di tengah jam perdagangan bursa.
- **Prosedur Validasi:**
  1. Pada penutupan pasar harian ($t$), sistem memeriksa:
     $$\text{Apakah } \text{Close}_t < \text{Stop Price}_t \text{ ?}$$
  2. Jika **YA**: Order likuidasi posisi ditempatkan untuk dieksekusi pada harga **OPEN hari bursa berikutnya ($t+1$)**.
  3. Jika **TIDAK** (misal *Low* sempat menembus stop namun *Close* kembali memantul di atas stop): Posisi **TETAP DIPERTAHANKAN**. Posisi terlindungi dari manipulasi *spread* dan kepanikan sesaat.

---

### 4.3. Patah Tren Struktural (Trend Invalidation Exit)
*Menghindari Penurunan Katastropik (Dead Money)*

Posisi wajib dilikuidasi penuh pada *Open* hari berikutnya tanpa memandang level harga beli jika terjadi salah satu dari kondisi struktural berikut:
1. **Penembusan Moving Average Kritis:**
   Harga penutupan harian konfirmasi berada di bawah $\text{SMA}_{50}$ selama 2 hari berturut-turut dengan volume di atas rata-rata.
2. **Breakdown Struktur Swing Low:**
   Harga penutupan menembus ke bawah batas swing low 20-hari ($\text{Close} < \text{Swing Low}_{20}$), menandakan siklus *higher highs / higher lows* telah berakhir.
3. **Reversal Breakdown HVN:**
   Harga menembus ke bawah rak HVN pendukung dan terjerembap masuk ke dalam jurang LVN bawah dengan volume distribusi masif.

---

### 4.4. Aksi Ambil Untung Saat Overbought Ekstrem (Scale-Out Take Profit)

Untuk mengamankan profit sebelum fase koreksi keras atau *climax top*:
- **Pemicu Sinyal:**
  1. $\text{RSI}_{14} \ge 80 - 85$ (Kondisi overbought ekstrem).
  2. **DAN** harga mendekati batas atas rak HVN sekunder atau zona ekstensi Fibonacci $\ge 2.0\times$ ATR dari $\text{SMA}_{20}$.
- **Tindakan Taktis:**
  - Jual sebagian posisi (**trim 25% – 33%**) untuk mengunci likuiditas keuntungan.
  - Sisa 67% – 75% posisi tetap dibiarkan bergulir (*let winners run*) dengan menaikkan Trailing Stop lebih ketat ke $\text{SMA}_{20}$.

---

## 5. Pilar 4: Smart Band Rebalancing & Holding Hysteresis Buffer

### 5.1. Prinsip Utama: "Trailing Stop > Auto Rebalance" (Holding Hysteresis Buffer)

Salah satu penyebab underperformance terbesar sistem lama adalah *calendar rebalance churn*: setiap siklus rebalance 5 hari, sistem melikuidasi atau memangkas posisi saham unggulan yang sedang dalam fase *super compounding* hanya karena skor momentum relatif jangka pendek berfluktuasi tipis (misal rotasi prematur keluar dari PLTR, AMD, DASH, INTC, MU).

Dalam arsitektur baru, berlaku aturan absolut: **"Trailing Stop > Auto Rebalance"**. Posisi yang sedang berjalan dilindungi oleh *Holding Hysteresis Buffer*.

#### Kriteria Retensi Posisi Sehat (Healthy Holdings Preservation):
Sebuah posisi aktif **DILARANG DILIKUIDASI ATAU DI-DROP** oleh rebalance kalender jika memenuhi ketiga kriteria kesehatan struktural berikut:
1. **Tren Struktural Sehat:** $\text{Close} \ge 0.98 \times \text{SMA}_{50}$ (tidak mengalami *trend breakdown* mayor).
2. **Level Stop Utuh:** $\text{Close} \ge \text{Stop Price}$ (posisi tidak melanggar batas proteksi risiko).
3. **Bukan Overbought Parah:** $\text{RSI}_{14} \le \text{Take Profit RSI}$ (misal $\le 82$, atau berstatus *Super Runner* yang dikecualikan untuk membiarkan tren berlari).

#### Aturan Penggantian Saham (Replacement Hurdle):
Jika ada kandidat baru dari screening universe yang memiliki skor menarik, sistem **HANYA BOLEH menggantikan** posisi sehat yang sudah ada jika selisih skor momentum kandidat baru melampaui *hurdle threshold* signifikan:
$$\Delta \text{Score} = \text{Score}_{\text{new}} - \text{Score}_{\text{holding}} \ge \mathbf{0.20}$$
Jika tidak melampaui hurdle 0.20, pemenang yang sedang berjalan **TETAP DIPERTAHANKAN**.

#### Logika Manajemen Keluar (Exit Delegation):
- Likuidasi keluar (*exit*) didelegasikan sepenuhnya kepada **Trailing Stop dinamis**, bukan kepada rebalance periodik.
- *Healthy compounding winners* dibiarkan bergulir menangkap tren eksponensial ratusan persen.
- Rebalance hanya memangkas porsi ekstrem (*asymmetric band trimming*) jika bobot posisi melampaui toleransi portofolio (misal $> 29\%$).

---

### 5.2. Deadband Threshold (Kebijakan Anti-Micro Churn)
Pada model terdahulu, terjadi 476 transaksi *trim* dengan rata-rata nilai transaksi hanya $8.87 karena ketiadaan batas toleransi pergeseran portofolio.

#### Aturan Eksekusi Rebalancing:
Sistem dilarang mengeksekusi rebalance/trim jika selisih bobot aktual terhadap bobot target tidak melampaui batas ambang (*deadband threshold*):

$$\text{Eksekusi Rebalance HANYA JIKA:}$$
$$|\text{Bobot Target} - \text{Bobot Aktual}| \ge \mathbf{3.0\%} \quad \text{DAN} \quad |\text{Nilai Nominal Perubahan}| \ge \mathbf{\$30.00}$$

- **Manfaat Nyata:**
  1. Mengeliminasi $>70\%$ transaksi mikro tanpa nilai tambah.
  2. Menghemat biaya komisi/fee drag hingga 60–80%.
  3. Membiarkan posisi saham unggulan melakukan *compounding* bebas tanpa dipangkas setiap minggu.

---

### 5.3. Aturan Alokasi Kas Dinamis (Regime-Based Cash Buffer)

Menghindari kesalahan fatal April–Mei 2025 di mana portofolio memegang 88.5% kas dan berotasi ke saham defensif saat reli pasar dimulai. Cadangan kas ditentukan secara objektif oleh **Rezim Pasar Benchmark (SPY)**:

| Rezim Pasar | Kondisi Kuantitatif SPY | Target Cash Buffer | Target Ekuitas Terinvestasi | Sikap Portofolio & Karakter Aset |
| :--- | :--- | :---: | :---: | :--- |
| **BULL REGIME** | $\text{SPY} \ge \text{SMA}_{50}$ | **0% – 5%** | **95% – 100%** | **Aggressive Alpha:** Fully invested pada saham *top momentum*, semikonduktor, AI, teknologi ber-beta tinggi. Dilarang parkir di kas. |
| **PULLBACK / NEUTRAL**| $\text{SMA}_{200} \le \text{SPY} < \text{SMA}_{50}$ | **25% – 35%** | **65% – 75%** | **Selective Quality:** Sisihkan kas untuk menyerap peluang reversal/pullback. Alokasikan hanya pada setup dengan konfirmasi volume tertinggi. |
| **BEAR REGIME** | $\text{SPY} < \text{SMA}_{200}$ | **80% – 100%** | **0% – 20%** | **Capital Preservation:** Defensif penuh. Potong posisi yang melemah, pertahankan kas hingga SPY kembali menembus ke atas $\text{SMA}_{200}$. |

```
                       REKONSILIASI KAS BERDASARKAN SPY
               
        SPY Harga
           ^
           |     [ BULL REGIME ]              Cash 0% - 5%
  SMA50  --+--------------------------------- Fully Invested in Momentum
           |     [ PULLBACK / CHOPPY ]        Cash 25% - 35%
  SMA200 --+--------------------------------- Selective Quality Setups
           |     [ BEAR REGIME ]              Cash 80% - 100%
           |                                  Preserve Capital & Stand Aside
           +--------------------------------------------------------> Waktu
```

---

## 6. SOP Checklist Keputusan Periodik

Gunakan alur keputusan berikut setiap kali siklus review periodik dijalankan (misal tiap 5 hari bursa):

### Langkah 1: Diagnosis Rezim Pasar (Market Benchmark Check)
- [ ] Periksa harga SPY terhadap $\text{SMA}_{50}$ dan $\text{SMA}_{200}$.
- [ ] Tentukan target pagu kas: Bull ($0\%$), Pullback ($25\%$), atau Bear ($80\%-100\%$).

### Langkah 2: Audit Posisi Aktif & Hysteresis Buffer Check
- [ ] **Cek Stop Loss EOD:** Apakah ada posisi dengan $\text{Close} < \text{Trailing Stop Price}$? $\rightarrow$ *Tandai untuk SELL Open besok (Exit via Trailing Stop).*
- [ ] **Cek Patah Tren:** Apakah ada posisi non-reversal dengan $\text{Close} < 0.98 \times \text{SMA}_{50}$? $\rightarrow$ *Tandai untuk SELL.*
- [ ] **Cek Overbought Ekstrem:** Apakah non-runner mencatat $\text{RSI}_{14} > 82$ di resistance LVN? $\rightarrow$ *Tandai untuk TRIM.*
- [ ] **Kunci Hysteresis ("Trailing Stop > Auto Rebalance"):** Jika $\text{Close} \ge 0.98 \times \text{SMA}_{50}$, stop belum tersentuh, dan RSI wajar, **WAJIB PERTAHANKAN** (jangan drop karena rebalance rutin).
- [ ] **Update High-Water Mark & Dynamic Stop Lifecycle:** Perbarui HWM dan trailing stop; untuk reversal: kunci Breakeven di $+8\%$ dan Runner Trail 12% di $+20\%$.
### Langkah 3: Penapisan Kandidat Baru (Universe Screening)
- [ ] Identifikasi kandidat yang lolos salah satu dari 3 Taksonomi Setup:
  - **Continuation:** Breakout high 20-bar ($\text{Close} \ge 0.97 \times \text{High}_{20}$) + Volume $\ge 1.25\times$ + **Bullish Accumulation Candle wajib ($\text{last\_c} \ge \text{last\_o}$)**.
  - **Pullback:** Retest SMA20/50 di support HVN + Volume $< 1.15\times$ + RSI 35-50 + Bounce.
  - **Reversal:** Rejection di 60d low / support POC + Volume $\ge 1.40\times$ + Rejection wick $\ge 50\%$ (Initial tight stop 4.5%-5.0%).
- [ ] Urutkan kandidat berdasarkan kekuatan momentum relatif. Kandidat baru hanya boleh menggantikan posisi sehat jika $\Delta \text{Score} \ge 0.20$.
### Langkah 4: Filter Deadband & Eksekusi Order
- [ ] Bandingkan alokasi saat ini terhadap target model.
- [ ] Hapus semua transaksi *trim/rebalance* yang perubahannya $< 3.0\%$ atau $<\$30$.
- [ ] Eksekusi order bersih pada pembukaan sesi bursa berikutnya (*Next Day Open*).

---
*Dokumen ini merupakan standar baku operasional strategi kuantitatif. Segala perubahan parameter wajib diuji melalui walk-forward backtest sebelum diimplementasikan.*
