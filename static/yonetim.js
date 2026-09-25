// Sayı kutusu odaktayken fare tekerleği değeri değiştiriyordu: yönetici
// sayfayı kaydırırken bayiye yüklenen tutar sessizce artıp azalıyordu.
// Tekerlek sayfayı kaydırsın, kutuya dokunmasın.
document.addEventListener(
  "wheel",
  function (olay) {
    var kutu = olay.target;
    if (kutu instanceof HTMLInputElement && kutu.type === "number" && kutu === document.activeElement) {
      kutu.blur();
    }
  },
  { passive: true }
);
