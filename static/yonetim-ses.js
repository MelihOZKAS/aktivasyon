// Yeni iş gelince "çın": yeni başvuru, bayi başvurusu, ödeme bildirimi ve
// kontör siparişi. Panel açık duran yönetici başka sekmedeyken de duysun;
// rozetler ancak sayfa yenilenince değişiyordu.
//
// Ses dosya değil, burada üretilen kısa bir zil (Web Audio): dışarıdan
// indirilen bir dosyaya, lisansına ve yüklenmesine bağlı değil.
//
// Sayfa açılınca gelen ilk cevap yalnızca başlangıçtır, ses çalmaz —
// her sayfa geçişinde birikmiş kayıtlar için çınlamasın. Birden çok sekme
// açıksa aynı kayıt için tek sekme çalar (son çalınan numaralar
// localStorage'da ortak).
(function () {
  if (window.top !== window || /[?&]_popup=1/.test(location.search)) return;

  var ADRES = "/yonetim/yeni-kayitlar/";
  var ARALIK = 15000;
  var ORTAK = "yonetim-cin";
  var taban = null;
  var baglam = null;

  function sesBaglami() {
    var Sinif = window.AudioContext || window.webkitAudioContext;
    if (!Sinif) return null;
    if (!baglam) baglam = new Sinif();
    if (baglam.state === "suspended") baglam.resume();
    return baglam;
  }

  // Tarayıcı sesi sayfayla etkileşimden sonra açar; ilk dokunuşta hazırla.
  ["pointerdown", "keydown"].forEach(function (olay) {
    document.addEventListener(olay, sesBaglami, { once: true, capture: true });
  });

  // Küçük zil: temel ton ve zilin uyumsuz iki üst tonu; üst tonlar daha
  // çabuk söner, "çın" o. Toplam 1 saniyenin altında.
  function cal() {
    var c = sesBaglami();
    if (!c) return;
    var t = c.currentTime + 0.02;
    var cikis = c.createGain();
    cikis.gain.value = 0.3;
    cikis.connect(c.destination);
    [[1568, 1, 0.9], [4327, 0.35, 0.35], [8467, 0.12, 0.15]].forEach(function (ton) {
      var osilator = c.createOscillator();
      var kazanc = c.createGain();
      osilator.type = "sine";
      osilator.frequency.value = ton[0];
      kazanc.gain.setValueAtTime(0.0001, t);
      kazanc.gain.exponentialRampToValueAtTime(ton[1], t + 0.004);
      kazanc.gain.exponentialRampToValueAtTime(0.0001, t + ton[2]);
      osilator.connect(kazanc);
      kazanc.connect(cikis);
      osilator.start(t);
      osilator.stop(t + ton[2] + 0.05);
    });
  }

  function ortagiOku() {
    try { return JSON.parse(localStorage.getItem(ORTAK)) || {}; } catch (e) { return {}; }
  }

  function ortagaYaz(deger) {
    try { localStorage.setItem(ORTAK, JSON.stringify(deger)); } catch (e) {}
  }

  function degerlendir(yeni) {
    if (taban === null) { taban = yeni; return; }
    var anahtarlar = Object.keys(yeni);
    var artti = anahtarlar.some(function (k) { return yeni[k] > (taban[k] || 0); });
    taban = yeni;
    if (!artti) return;
    var ortak = ortagiOku();
    var ilkGoren = anahtarlar.some(function (k) { return yeni[k] > (ortak[k] || 0); });
    anahtarlar.forEach(function (k) { ortak[k] = Math.max(yeni[k], ortak[k] || 0); });
    ortagaYaz(ortak);
    if (ilkGoren) cal();
  }

  function sor() {
    fetch(ADRES, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (yanit) {
        if (yanit.status === 403) return false; // oturum düştü ya da personel değil: dur
        if (!yanit.ok) return true;
        return yanit.json().then(function (veri) { degerlendir(veri); return true; });
      })
      .catch(function () { return true; })
      .then(function (devam) { if (devam) setTimeout(sor, ARALIK); });
  }

  sor();
})();
