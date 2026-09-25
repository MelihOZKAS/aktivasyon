// Kamerayla SIM barkodu okutma (yönetim paneli).
//
// Kartlar koli koli geliyor; 19-20 haneyi elle yazmak ya da her kart için
// ayrı bir okuyucu cihaz aramak günlük işi yavaşlatıyordu. `data-barkod`
// taşıyan kutunun yanına "Barkod okut" düğmesi konur:
//   data-barkod="tek"   → okunan kod kutuya yazılır, kamera kapanır
//                         (tekli SIM ekleme).
//   data-barkod="liste" → kamera açık kalır, her yeni kod listeye bir satır
//                         olarak eklenir; listede olan kod atlanır (toplu ekle).
//
// Klavye gibi yazan USB/Bluetooth okuyucu için bir şey gerekmez, kutuya
// doğrudan yazar. Bu dosya tablet/telefon kamerası içindir.
//
// Çözücü: tarayıcının kendi BarcodeDetector'ı varsa o (Android Chrome —
// hızlı, küçük barkodda iyi), yoksa ZXing ilk basışta CDN'den yüklenir
// (iOS Safari). Kamera yalnızca HTTPS'te açılır.
(function () {
  "use strict";

  var ZXING_ADRESI = "https://cdn.jsdelivr.net/npm/@zxing/browser@0.2.1/umd/zxing-browser.min.js";
  var ZXING_OZETI = "sha384-HRtzk9lZgkbSgvUyQrnfC/GxiXZgwaNyD7hC9wcXlsBpDhkS80ISl73juef2FRuf";
  var BICIMLER = ["code_128", "code_39", "ean_13", "itf", "data_matrix", "qr_code"];
  // SIM/IMEI'de beklenen: rakam ve harf, 6-40 karakter. Barkodun başına
  // sonuna eklenen boşluk ve kontrol karakterleri atılır.
  var GECERLI = /^[0-9A-Za-z-]{6,40}$/;

  function stil(el, css) { el.style.cssText = css; return el; }

  function bip() {
    try {
      var ses = new (window.AudioContext || window.webkitAudioContext)();
      var osc = ses.createOscillator();
      var kazanc = ses.createGain();
      osc.frequency.value = 1760;
      kazanc.gain.value = 0.08;
      osc.connect(kazanc); kazanc.connect(ses.destination);
      osc.start(); osc.stop(ses.currentTime + 0.09);
      osc.onended = function () { ses.close(); };
    } catch (e) { /* ses yoksa titreşim yeter */ }
    if (navigator.vibrate) navigator.vibrate(60);
  }

  function zxingYukle() {
    if (window.ZXingBrowser) return Promise.resolve(window.ZXingBrowser);
    return new Promise(function (tamam, hata) {
      var s = document.createElement("script");
      s.src = ZXING_ADRESI;
      s.integrity = ZXING_OZETI;
      s.crossOrigin = "anonymous";
      s.onload = function () { tamam(window.ZXingBrowser); };
      s.onerror = function () { hata(new Error("Barkod çözücü yüklenemedi; bağlantıyı kontrol edin.")); };
      document.head.appendChild(s);
    });
  }

  function yerliDedektor() {
    if (!("BarcodeDetector" in window)) return Promise.resolve(null);
    return window.BarcodeDetector.getSupportedFormats().then(function (desteklenen) {
      var bicimler = BICIMLER.filter(function (b) { return desteklenen.indexOf(b) !== -1; });
      return bicimler.length ? new window.BarcodeDetector({ formats: bicimler }) : null;
    }).catch(function () { return null; });
  }

  // -- ekran ------------------------------------------------------------

  function ekranKur(coklu) {
    var perde = stil(document.createElement("div"),
      "position:fixed;inset:0;z-index:9999;background:#0b0f17;display:flex;flex-direction:column;" +
      "color:#fff;font:15px/1.4 system-ui,-apple-system,sans-serif");
    perde.setAttribute("role", "dialog");
    perde.setAttribute("aria-modal", "true");
    perde.setAttribute("aria-label", "Barkod okut");

    var sahne = stil(document.createElement("div"), "position:relative;flex:1;overflow:hidden");
    var video = stil(document.createElement("video"), "width:100%;height:100%;object-fit:cover");
    video.setAttribute("playsinline", "");
    video.setAttribute("muted", "");
    video.muted = true;
    // Barkodu tutacağı yer: geniş ve alçak, SIM barkodu yataydır.
    var cerceve = stil(document.createElement("div"),
      "position:absolute;left:8%;right:8%;top:38%;height:24%;border:2px solid rgba(255,255,255,.9);" +
      "border-radius:10px;box-shadow:0 0 0 100vmax rgba(0,0,0,.45);transition:border-color .15s");
    sahne.appendChild(video); sahne.appendChild(cerceve);

    var alt = stil(document.createElement("div"),
      "padding:14px 16px calc(14px + env(safe-area-inset-bottom));display:flex;flex-direction:column;gap:10px");
    var durum = stil(document.createElement("p"), "margin:0;min-height:1.4em;text-align:center");
    durum.setAttribute("aria-live", "polite");
    durum.textContent = "Kamera açılıyor…";
    var son = stil(document.createElement("p"),
      "margin:0;min-height:1.4em;text-align:center;font:600 17px/1.4 ui-monospace,monospace;letter-spacing:.02em");
    var kapat = stil(document.createElement("button"),
      "min-height:48px;border:0;border-radius:10px;background:#fff;color:#0b0f17;font:600 16px system-ui,sans-serif;cursor:pointer");
    kapat.type = "button";
    kapat.textContent = coklu ? "Bitti" : "Vazgeç";
    alt.appendChild(durum); alt.appendChild(son); alt.appendChild(kapat);

    perde.appendChild(sahne); perde.appendChild(alt);
    document.body.appendChild(perde);
    var eskiTasma = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return {
      video: video, durum: durum, son: son, kapat: kapat,
      yak: function (renk) {
        cerceve.style.borderColor = renk;
        setTimeout(function () { cerceve.style.borderColor = "rgba(255,255,255,.9)"; }, 350);
      },
      kaldir: function () { perde.remove(); document.body.style.overflow = eskiTasma; },
    };
  }

  // -- okuma ------------------------------------------------------------

  function okut(kutu) {
    var coklu = kutu.dataset.barkod === "liste";
    var ekran = ekranKur(coklu);
    var durdur = function () {};
    var bitti = false;
    var sonKod = "", sonZaman = 0, eklenen = 0;

    function kapat() {
      if (bitti) return;
      bitti = true;
      durdur();
      ekran.kaldir();
      document.removeEventListener("keydown", tus);
      kutu.dispatchEvent(new Event("input", { bubbles: true }));
      kutu.focus();
    }
    function tus(olay) { if (olay.key === "Escape") kapat(); }
    document.addEventListener("keydown", tus);
    ekran.kapat.addEventListener("click", kapat);

    function listedeki() {
      return kutu.value.split(/[\s,;|]+/).filter(Boolean);
    }

    function okundu(ham) {
      var kod = String(ham || "").replace(/[\s\u0000-\u001f]+/g, "");
      if (!GECERLI.test(kod)) return;
      // Kamera aynı barkodu saniyede birkaç kez okur; aynı kodu hemen
      // ikinci kez işlememek için kısa bir bekleme.
      var simdi = Date.now();
      if (kod === sonKod && simdi - sonZaman < 2500) return;
      sonKod = kod; sonZaman = simdi;

      if (!coklu) {
        kutu.value = kod;
        bip();
        kapat();
        return;
      }
      if (listedeki().indexOf(kod) !== -1) {
        ekran.durum.textContent = "Bu kart zaten listede — atlandı.";
        ekran.son.textContent = kod;
        ekran.yak("#f59e0b");
        if (navigator.vibrate) navigator.vibrate([40, 60, 40]);
        return;
      }
      var deger = kutu.value.replace(/\s+$/, "");
      kutu.value = (deger ? deger + "\n" : "") + kod + "\n";
      kutu.dispatchEvent(new Event("input", { bubbles: true }));
      eklenen += 1;
      bip();
      ekran.yak("#16a34a");
      ekran.son.textContent = kod;
      ekran.durum.textContent = eklenen + " kart eklendi · listede " + listedeki().length + " kart. Sıradakini tut.";
    }

    function hataGoster(hata) {
      var ad = hata && hata.name;
      ekran.durum.textContent =
        ad === "NotAllowedError" ? "Kamera izni verilmedi. Tarayıcı ayarlarından bu siteye kamera izni verin." :
        ad === "NotFoundError" ? "Bu cihazda kamera bulunamadı." :
        !window.isSecureContext ? "Kamera yalnızca güvenli (https) bağlantıda açılır." :
        (hata && hata.message) || "Kamera açılamadı.";
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      hataGoster(new Error(window.isSecureContext ? "Bu tarayıcı kamerayı desteklemiyor." : ""));
      return;
    }

    var kamera = { video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false };
    var bekleme = coklu ? "Barkodu çerçeveye tut; her kart listeye eklenir." : "Barkodu çerçeveye tut.";

    yerliDedektor().then(function (dedektor) {
      if (bitti) return;
      if (dedektor) {
        return navigator.mediaDevices.getUserMedia(kamera).then(function (akis) {
          if (bitti) { akis.getTracks().forEach(function (t) { t.stop(); }); return; }
          ekran.video.srcObject = akis;
          return ekran.video.play().then(function () {
            ekran.durum.textContent = bekleme;
            var zamanlayici = setInterval(function () {
              if (ekran.video.readyState < 2) return;
              dedektor.detect(ekran.video).then(function (sonuclar) {
                if (sonuclar.length) okundu(sonuclar[0].rawValue);
              }).catch(function () {});
            }, 150);
            durdur = function () {
              clearInterval(zamanlayici);
              akis.getTracks().forEach(function (t) { t.stop(); });
            };
          });
        });
      }
      return zxingYukle().then(function (ZX) {
        if (bitti) return;
        var okuyucu = new ZX.BrowserMultiFormatReader();
        return okuyucu.decodeFromConstraints(kamera, ekran.video, function (sonuc) {
          if (sonuc) okundu(sonuc.getText());
        }).then(function (kontrol) {
          if (bitti) { kontrol.stop(); return; }
          ekran.durum.textContent = bekleme;
          durdur = function () { kontrol.stop(); };
        });
      });
    }).catch(hataGoster);
  }

  // -- düğmeler ---------------------------------------------------------

  function dugmeEkle(kutu) {
    if (kutu.dataset.barkodBagli) return;
    kutu.dataset.barkodBagli = "1";
    var dugme = stil(document.createElement("button"),
      "display:inline-flex;align-items:center;gap:6px;margin-top:8px;min-height:44px;padding:0 14px;" +
      "border:1px solid currentColor;border-radius:8px;background:transparent;color:inherit;font-weight:600;font-size:14px;cursor:pointer");
    dugme.type = "button";
    dugme.innerHTML =
      '<span class="material-symbols-outlined" aria-hidden="true" style="font-size:20px">barcode_scanner</span>' +
      (kutu.dataset.barkod === "liste" ? "Kamerayla okut (sırayla)" : "Barkod okut");
    dugme.addEventListener("click", function () { okut(kutu); });
    kutu.insertAdjacentElement("afterend", dugme);
  }

  function bagla() {
    document.querySelectorAll("[data-barkod]").forEach(dugmeEkle);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bagla);
  else bagla();
})();
