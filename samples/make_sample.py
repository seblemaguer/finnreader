"""Build a small Finnish test PDF with an outline, dialog and a hyphenated line break."""
import sys
import pymupdf

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
doc = pymupdf.open()
texts = [
    ("Ensimmäinen luku", "Talo oli vanha ja punainen. Sen ikkunat olivat pienet, esim. keittiön ikkuna. Matti asui siellä yksin.\n\n– Mitä sinä teet? hän kysyi.\n\n– Luen kirjaa, Liisa vastasi. – Se on hyvin kiinnostava.\n\nHän sanoi: ”Tule tänne!” ja nauroi. Ulkona satoi lunta koko päivän ja ilta oli pimeä ja kylmä ja hiljai-\nnen."),
    ("Toinen luku", "Aamulla aurinko paistoi. Matti joi kahvia keittiössä.\n\n”Onko sinulla nälkä?” Liisa kysyi. ”Minulla on.”\n\n– Mitä teet? Matti kysyi. – Tule tänne! Nyt heti."),
]
toc = []
for title, body in texts:
    page = doc.new_page()
    page.insert_text((72, 80), title, fontsize=18, fontname="F0", fontfile=FONT)
    page.insert_textbox(pymupdf.Rect(72, 110, 520, 700), body, fontsize=12, fontname="F0", fontfile=FONT)
    page.insert_text((300, 800), str(page.number + 1), fontsize=10)
    toc.append([1, title, page.number + 1])
doc.set_toc(toc)
doc.set_metadata({"title": "Testikirja"})
doc.save(sys.argv[1])
