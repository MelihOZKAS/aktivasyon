// Yeni iş gelince "çın": yeni başvuru, bayi başvurusu, ödeme bildirimi ve
// kontör siparişi. Panel açık duran yönetici başka sekmedeyken de duysun;
// rozetler ancak sayfa yenilenince değişiyordu.
//
// Ses `static/ses/alarm.mp3`'tür (1 sn). Önce burada üretilen kısa bir zil
// çalıyordu (Web Audio, osilatör); yönetim "çok pasif" dedi, başka sekmede
// duyulmuyordu. Dosya ilk dokunuşta bir kez indirilip çözülür, her çalışta
// aynı tampon kullanılır. Adres sabit: WhiteNoise hash'siz adı da sunar.
//
// Sayfa açılınca gelen ilk cevap yalnızca başlangıçtır, ses çalmaz —
// her sayfa geçişinde birikmiş kayıtlar için çınlamasın. Birden çok sekme
// açıksa aynı kayıt için tek sekme çalar (son çalınan numaralar
// localStorage'da ortak).
(function () {
  if (window.top !== window || /[?&]_popup=1/.test(location.search)) return;

  var ADRES = "/yonetim/yeni-kayitlar/";
  var ARALIK = 15000;
  var SES = "/static/ses/alarm.mp3";
  var ORTAK = "yonetim-cin";
  var KAZANC = 3;
  var taban = null;
  var baglam = null;
  var tampon = null;
  var yukleme = null;

  function sesBaglami() {
    var Sinif = window.AudioContext || window.webkitAudioContext;
    if (!Sinif) return null;
    if (!baglam) baglam = new Sinif();
    if (baglam.state === "suspended") baglam.resume();
    return baglam;
  }

  // Dosya bir kez iner ve çözülür. İnemezse sonraki çalışta yeniden denenir.
  function sesiHazirla(c) {
    if (!yukleme) {
      yukleme = fetch(SES, { credentials: "same-origin" })
        .then(function (yanit) {
          if (!yanit.ok) throw new Error(yanit.status);
          return yanit.arrayBuffer();
        })
        .then(function (veri) {
          // Geri çağırımlı biçim: eski Safari'de decodeAudioData söz vermiyor.
          return new Promise(function (coz, reddet) { c.decodeAudioData(veri, coz, reddet); });
        })
        .then(function (cozulmus) { tampon = cozulmus; })
        .catch(function () { yukleme = null; });
    }
    return yukleme;
  }

  // Tarayıcı sesi sayfayla etkileşimden sonra açar; ilk dokunuşta hazırla.
  ["pointerdown", "keydown"].forEach(function (olay) {
    document.addEventListener(olay, function () {
      var c = sesBaglami();
      if (c) sesiHazirla(c);
    }, { once: true, capture: true });
  });

  function cal() {
    var c = sesBaglami();
    if (!c) return;
    sesiHazirla(c).then(function () {
      if (!tampon) return;
      var kaynak = c.createBufferSource();
      kaynak.buffer = tampon;
      // Dosya kısık kayıtlı: %100'ün üstüne çıkarıp (x3) sınırlayıcıdan
      // geçiriyoruz ki yükselen ses patlamasın.
      var kazanc = c.createGain();
      kazanc.gain.value = KAZANC;
      var sinirlayici = c.createDynamicsCompressor();
      sinirlayici.threshold.value = -6;
      sinirlayici.knee.value = 0;
      sinirlayici.ratio.value = 20;
      sinirlayici.attack.value = 0.001;
      sinirlayici.release.value = 0.1;
      kaynak.connect(kazanc);
      kazanc.connect(sinirlayici);
      sinirlayici.connect(c.destination);
      kaynak.start();
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
